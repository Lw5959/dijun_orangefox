/* 仅补齐新内核的固件读取权限，不改变 enforcing、未知权限处理或其他访问规则。
 * 使用 libsepol 3.5 读取完整策略；输入来源和输出 SHA 由装配脚本另行核验。 */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sepol/policydb/policydb.h>
#include <sepol/kernel_to_cil.h>

int main(int argc, char **argv) {
    if (argc != 3 && !(argc == 4 && (!strcmp(argv[3], "--roundtrip") || !strcmp(argv[3], "--cil")))) return 2;
    FILE *input = fopen(argv[1], "rb");
    if (!input) return 1;
    uint32_t string_length, original_config;
    assert(fseek(input, 4, SEEK_SET) == 0 && fread(&string_length, 4, 1, input) == 1);
    long config_offset = 12 + string_length;
    assert(fseek(input, config_offset, SEEK_SET) == 0 && fread(&original_config, 4, 1, input) == 1);
    rewind(input);
    policydb_t policy;
    policy_file_t file;
    assert(policydb_init(&policy) == 0);
    policy_file_init(&file);
    file.type = PF_USE_STDIO;
    file.fp = input;
    assert(policydb_read(&policy, &file, 0) == 0);
    fclose(input);

    if (argc == 4 && !strcmp(argv[3], "--cil")) {
        FILE *cil = fopen(argv[2], "w");
        assert(cil && sepol_kernel_policydb_to_cil(cil, &policy) == 0);
        assert(fclose(cil) == 0);
        policydb_destroy(&policy);
        return 0;
    }

    if (argc == 4) goto write_policy;

    class_datum_t *system = hashtab_search(policy.p_classes.table, "system");
    type_datum_t *kernel = hashtab_search(policy.p_types.table, "kernel");
    type_datum_t *firmware = hashtab_search(policy.p_types.table, "vendor_file");
    assert(system && kernel && firmware && !system->comdatum);
    assert(system->permissions.nprim == 6);
    assert(!hashtab_search(system->permissions.table, "firmware_load"));
    perm_datum_t *permission = calloc(1, sizeof(*permission));
    assert(permission);
    permission->s.value = ++system->permissions.nprim;
    assert(hashtab_insert(system->permissions.table, strdup("firmware_load"), permission) == 0);

    const unsigned bit = 1U << (permission->s.value - 1);
    // 运行时 KernelSU 的通配规则可能含尚未命名的高位。新权限变成已知名称后，
    // 不能顺带授权给这些旧规则；仅保留下面明确添加的 kernel -> vendor_file。
    avtab_t *tables[] = {&policy.te_avtab, &policy.te_cond_avtab};
    for (unsigned t = 0; t < 2; ++t)
        for (unsigned bucket = 0; bucket < tables[t]->nslot; ++bucket)
            for (avtab_ptr_t node = tables[t]->htable[bucket]; node; node = node->next)
                if (node->key.target_class == system->s.value && (node->key.specified & AVTAB_ALLOWED))
                    node->datum.data &= ~bit;
    avtab_key_t key = { .source_type = kernel->s.value, .target_type = firmware->s.value,
                       .target_class = system->s.value, .specified = AVTAB_ALLOWED };
    avtab_datum_t *rule = avtab_search(&policy.te_avtab, &key);
    if (rule) {
        rule->data |= bit;
    } else {
        avtab_datum_t added = { .data = bit };
        assert(avtab_insert(&policy.te_avtab, &key, &added) == 0);
    }
write_policy:;
    FILE *output = fopen(argv[2], "w+b");
    if (!output) return 1;
    file.fp = output;
    assert(policydb_write(&policy, &file) == 0);
    // Android 的两个 netlink 配置位不在上游 libsepol 3.5 中，原样保留。
    // 其余配置必须仍等于原件，不能借此次修改放宽 unknown 或 permissive 行为。
    uint32_t written_config;
    assert(fseek(output, config_offset, SEEK_SET) == 0 && fread(&written_config, 4, 1, output) == 1);
    assert(written_config == (original_config & ~UINT32_C(0xc0000000)));
    assert(fseek(output, config_offset, SEEK_SET) == 0 && fwrite(&original_config, 4, 1, output) == 1);
    assert(fclose(output) == 0);
    printf("%s; handle_unknown=%u; config=%08x\n",
           argc == 4 ? "unchanged roundtrip" : "allow kernel vendor_file:system firmware_load",
           policy.handle_unknown, original_config);
    policydb_destroy(&policy);
    return 0;
}
