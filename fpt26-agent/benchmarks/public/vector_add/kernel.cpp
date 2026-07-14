static const int VECTOR_ADD_SIZE = 16;

extern "C" void vector_add(
    const int a[VECTOR_ADD_SIZE],
    const int b[VECTOR_ADD_SIZE],
    int c[VECTOR_ADD_SIZE]
)
{
    for (int i = 0; i < VECTOR_ADD_SIZE; ++i) {
        c[i] = a[i] + b[i];
    }
}
