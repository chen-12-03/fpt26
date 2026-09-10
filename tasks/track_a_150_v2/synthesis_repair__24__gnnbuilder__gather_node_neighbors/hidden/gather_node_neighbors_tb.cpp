#include "gather_node_neighbors.h"

int main() {
    const int node = 11;
    const int node_in_degree = 9;
    int node_neighbors[MAX_NODES] = {};
    int neighbor_table_offsets[MAX_NODES] = {};
    int neighbor_table[MAX_EDGES] = {};
    neighbor_table_offsets[node] = 41;
    for (int i = 0; i < node_in_degree; ++i)
        neighbor_table[41 + i] = 11 * i + 5;

    gather_node_neighbors(
        node,
        node_in_degree,
        node_neighbors,
        neighbor_table_offsets,
        neighbor_table);

    for (int i = 0; i < node_in_degree; ++i)
        if (node_neighbors[i] != 11 * i + 5)
            return 1;
    return 0;
}
