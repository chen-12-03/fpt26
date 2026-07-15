#include "residual.h"
#include "hls_stream.h"

// stage A drives the main path and the skip path.
static void stageA(data_t in[N], hls::stream<data_t> &s_main,
                   hls::stream<data_t> &s_skip) {
    // FIXED: Interleave writes to both streams to maintain rate balance
    // This prevents the RTL FIFOs from filling up due to burst writes
    for (int i = 0; i < N; i++) {
        s_main.write(in[i]);
        s_skip.write(in[i]);
    }
}

static void stageB(hls::stream<data_t> &s_main, hls::stream<data_t> &s_f) {
    for (int i = 0; i < N; i++) s_f.write(s_main.read() * 2);
}

static void stageC(hls::stream<data_t> &s_f, hls::stream<data_t> &s_skip,
                   data_t out[N]) {
    for (int i = 0; i < N; i++) out[i] = s_f.read() + s_skip.read();
}

void residual(data_t in[N], data_t out[N]) {
#pragma HLS DATAFLOW
    hls::stream<data_t> s_main, s_f, s_skip;
    stageA(in, s_main, s_skip);
    stageB(s_main, s_f);
    stageC(s_f, s_skip, out);
}
