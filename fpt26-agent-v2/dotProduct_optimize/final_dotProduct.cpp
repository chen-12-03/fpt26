// dotProduct.cpp
#include "dotProduct.h"

// Optimized: parallel computation with unrolling and pipelining
FeatureType
dotProduct(FeatureType param[NUM_FEATURES], DataType feature[NUM_FEATURES]) {
    // Partition arrays to enable parallel access
    #pragma HLS ARRAY_PARTITION variable=param complete dim=1
    #pragma HLS ARRAY_PARTITION variable=feature complete dim=1
    
    // Local variables for partial sums
    FeatureType partial_sum[PAR_FACTOR];
    #pragma HLS ARRAY_PARTITION variable=partial_sum complete dim=1
    
    // Initialize partial sums
    INIT_LOOP: for (int p = 0; p < PAR_FACTOR; p++) {
        #pragma HLS UNROLL
        partial_sum[p] = 0;
    }
    
    // Main computation loop - process PAR_FACTOR elements in parallel
    COMPUTE_LOOP: for (int i = 0; i < NUM_FEATURES / PAR_FACTOR; i++) {
        #pragma HLS PIPELINE II=1
        
        MULT_ADD_LOOP: for (int p = 0; p < PAR_FACTOR; p++) {
            #pragma HLS UNROLL
            int idx = i * PAR_FACTOR + p;
            partial_sum[p] += param[idx] * feature[idx];
        }
    }
    
    // Final reduction to combine all partial sums
    FeatureType result = 0;
    REDUCE_LOOP: for (int p = 0; p < PAR_FACTOR; p++) {
        #pragma HLS UNROLL
        result += partial_sum[p];
    }
    
    return result;
}
