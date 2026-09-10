
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

extern "C" void dummy_kernel(unsigned int* buffer0, unsigned int* buffer1, unsigned int size);

int main() {
    if (!std::freopen("track_a_hidden_stdout.actual", "wb", stdout)) return 97;
    if (!std::freopen("track_a_hidden_stderr.actual", "wb", stderr)) return 98;

  static unsigned int buffer0_storage[64] = {0};
  unsigned int* buffer0 = buffer0_storage;
    for (std::size_t track_a_i = 0; track_a_i < sizeof(buffer0_storage) / sizeof(buffer0_storage[0]); ++track_a_i) {
        buffer0_storage[track_a_i] = track_a_i * 29 + 7;
    }
  static unsigned int buffer1_storage[64] = {0};
  unsigned int* buffer1 = buffer1_storage;
  int size = 16;
  dummy_kernel(buffer0, buffer1, size);
  std::cout << "PASS\n";
  
    std::fprintf(stderr, "\nTRACK_A_OBSERVATION_BEGIN\n");
    std::fprintf(stderr, "buffer0_storage=%016llx\n", track_a_hash_bytes(&buffer0_storage, sizeof(buffer0_storage)));
    std::fprintf(stderr, "buffer1_storage=%016llx\n", track_a_hash_bytes(&buffer1_storage, sizeof(buffer1_storage)));
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
