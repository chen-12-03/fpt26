#include <cstdio>

static const int VECTOR_ADD_SIZE = 16;

extern "C" void vector_add(
    const int a[VECTOR_ADD_SIZE],
    const int b[VECTOR_ADD_SIZE],
    int c[VECTOR_ADD_SIZE]
);

int main()
{
    int a[VECTOR_ADD_SIZE];
    int b[VECTOR_ADD_SIZE];
    int c[VECTOR_ADD_SIZE];
    int expected[VECTOR_ADD_SIZE];

    for (int i = 0; i < VECTOR_ADD_SIZE; ++i) {
        a[i] = (i * 3) - 7;
        b[i] = 42 - (i * 2);
        c[i] = 0;
        expected[i] = a[i] + b[i];
    }

    vector_add(a, b, c);

    int errors = 0;
    for (int i = 0; i < VECTOR_ADD_SIZE; ++i) {
        if (c[i] != expected[i]) {
            std::printf(
                "Mismatch at index %d: got %d, expected %d\n",
                i,
                c[i],
                expected[i]
            );
            ++errors;
        }
    }

    if (errors != 0) {
        std::printf("vector_add failed: %d mismatches\n", errors);
        return 1;
    }

    std::printf("vector_add passed: %d elements checked\n", VECTOR_ADD_SIZE);
    return 0;
}
