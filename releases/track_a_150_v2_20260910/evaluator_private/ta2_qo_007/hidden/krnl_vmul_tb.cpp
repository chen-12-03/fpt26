
#include <cstdio>

static int track_a_compare_file(const char *actual_name, const char *golden_name) {
    FILE *actual = std::fopen(actual_name, "rb");
    FILE *golden = std::fopen(golden_name, "rb");
    if (!actual || !golden) {
        if (actual) std::fclose(actual);
        if (golden) std::fclose(golden);
        return 1;
    }
    int different = 0;
    for (;;) {
        int left = std::fgetc(actual);
        int right = std::fgetc(golden);
        if (left != right) different = 1;
        if (left == EOF || right == EOF) {
            if (left != right) different = 1;
            break;
        }
    }
    std::fclose(actual);
    std::fclose(golden);
    return different;
}


#include <cstddef>
#include <cstdint>
#include <cstdio>

static unsigned long long track_a_hash_bytes(const void *address, std::size_t size) {
    const unsigned char *bytes = static_cast<const unsigned char *>(address);
    unsigned long long value = 1469598103934665603ULL;
    for (std::size_t index = 0; index < size; ++index) {
        value ^= bytes[index];
        value *= 1099511628211ULL;
    }
    return value;
}

#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <ap_int.h>

extern "C" void krnl_vmul(int* a, int* b, int* c, const int length_r);

int main() {
    if (!std::freopen("track_a_hidden_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_hidden_stderr.actual", "wb", stderr)) return 98;

  static int a_storage[64] = {0};
  int* a = a_storage;
    for (std::size_t track_a_i = 0; track_a_i < sizeof(a_storage) / sizeof(a_storage[0]); ++track_a_i) {
        a_storage[track_a_i] = track_a_i * 29 + 7;
    }
  static int b_storage[64] = {0};
  int* b = b_storage;
    for (std::size_t track_a_i = 0; track_a_i < sizeof(b_storage) / sizeof(b_storage[0]); ++track_a_i) {
        b_storage[track_a_i] = track_a_i * 29 + 7;
    }
  static int c_storage[64] = {0};
  int* c = c_storage;
    for (std::size_t track_a_i = 0; track_a_i < sizeof(c_storage) / sizeof(c_storage[0]); ++track_a_i) {
        c_storage[track_a_i] = track_a_i * 29 + 7;
    }
  int length_r = 16;
  krnl_vmul(a, b, c, length_r);
  std::cout << "PASS\n";
  
    std::fprintf(stderr, "\nTRACK_A_OBSERVATION_BEGIN\n");
    std::fprintf(stderr, "a_storage=%016llx\n", track_a_hash_bytes(&a_storage, sizeof(a_storage)));
    std::fprintf(stderr, "b_storage=%016llx\n", track_a_hash_bytes(&b_storage, sizeof(b_storage)));
    std::fprintf(stderr, "c_storage=%016llx\n", track_a_hash_bytes(&c_storage, sizeof(c_storage)));
    std::fprintf(stderr, "TRACK_A_OBSERVATION_END\n");
    
    std::fflush(stdout);
    std::fflush(stderr);
    std::fclose(stdout);
    std::fclose(stderr);
    int track_a_mismatch = 0;
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stdout.actual", "track_a_hidden_stdout.golden");
    track_a_mismatch |= track_a_compare_file("track_a_hidden_stderr.actual", "track_a_hidden_stderr.golden");
    return track_a_mismatch ? 1 : 0;
}
