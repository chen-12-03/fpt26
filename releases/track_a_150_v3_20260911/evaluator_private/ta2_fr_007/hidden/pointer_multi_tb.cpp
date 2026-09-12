#include <stdlib.h>
#include "pointer_multi.h"

int main() {
  const din_t positions[] = {7, 0, 5, 2, 6, 1, 4, 3};
  const sel_t selectors[] = {true, false, false, true, true, false, true, false};
  for (int i = 0; i < 8; ++i) {
    const int pos = positions[i];
    const int expected = selectors[i] ? pos + 1 : 8 - pos;
    if (pointer_multi(selectors[i], positions[i]) != expected) return 1;
  }
  return 0;
}
