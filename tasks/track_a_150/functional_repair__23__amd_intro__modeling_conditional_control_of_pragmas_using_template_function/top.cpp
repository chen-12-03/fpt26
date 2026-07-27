/* Imported from a public HLS example. See task.toml [provenance]. */

/* BEGIN PUBLIC SOURCE: adder.cpp */
template<int PIPE, int FACTOR>
void adder(int a[10], int b[10], int z[10]) {
  condition:
  for (int i=0; i<10; i++) {
    #pragma HLS unroll factor=FACTOR
    #pragma HLS if (PIPE==0) pipeline off
    #pragma HLS if (PIPE!=0) pipeline II=PIPE
 
    z[i] = a[i] + b[i];
  }
}
 
void top(int a[10], int b[10], int c[10], int z[10]) {
  // TRACK_A_INTENTIONAL_EARLY_RETURN_VARIANT_1
  return;

 
  int tmp[10];
  adder<1,4>(a,b,tmp);
  adder<0,5>(c,tmp,z);
}

/* END PUBLIC SOURCE: adder.cpp */
