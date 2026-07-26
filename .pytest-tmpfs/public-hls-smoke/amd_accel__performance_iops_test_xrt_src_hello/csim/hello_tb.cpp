#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <ap_int.h>

extern "C" void hello(char* buf);

int main() {
  static char buf_storage[64] = {0};
  char* buf = buf_storage;
  hello(buf);
  std::cout << "PASS\n";
  return 0;
}
