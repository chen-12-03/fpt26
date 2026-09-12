#include "gather_node_neighbors.h"

int main() {
    const int node = 5;
    const int node_in_degree = 7;
    int node_neighbors[MAX_NODES] = {};
    int neighbor_table_offsets[MAX_NODES] = {};
    int neighbor_table[MAX_EDGES] = {};
    neighbor_table_offsets[node] = 23;
    for (int i = 0; i < node_in_degree; ++i)
        neighbor_table[23 + i] = 7 * i + 3;

    gather_node_neighbors(
        node,
        node_in_degree,
        node_neighbors,
        neighbor_table_offsets,
        neighbor_table);

    for (int i = 0; i < node_in_degree; ++i)
        if (node_neighbors[i] != 7 * i + 3)
            return 1;
    return 0;
}
