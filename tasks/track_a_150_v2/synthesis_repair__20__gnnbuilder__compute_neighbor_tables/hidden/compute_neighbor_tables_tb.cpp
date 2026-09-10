#include "compute_neighbor_tables.h"

int main() {
    const int num_nodes = 17;
    const int num_edges = 51;
    int in_degree_table[MAX_NODES] = {};
    int out_degree_table[MAX_NODES] = {};
    int neighbor_table_offsets[MAX_NODES] = {};
    int neighbor_table[MAX_EDGES] = {};
    int expected_offsets[MAX_NODES] = {};
    int expected_neighbors[MAX_EDGES] = {};
    int cursors[MAX_NODES] = {};
    int edge_list[MAX_EDGES][2] = {};
    for (int i = 0; i < num_edges; i++) {
        edge_list[i][0] = (i * 7 + 4) % num_nodes;
        edge_list[i][1] = (i * i + 5 * i + 3) % num_nodes;
        ++out_degree_table[edge_list[i][0]];
        ++in_degree_table[edge_list[i][1]];
    }
    for (int i = 1; i < num_nodes; ++i)
        expected_offsets[i] = expected_offsets[i - 1] + in_degree_table[i - 1];
    for (int i = 0; i < num_nodes; ++i)
        cursors[i] = expected_offsets[i];
    for (int i = 0; i < num_edges; ++i)
        expected_neighbors[cursors[edge_list[i][1]]++] = edge_list[i][0];

    compute_neighbor_tables(
        edge_list,
        in_degree_table,
        out_degree_table,
        neighbor_table_offsets,
        neighbor_table,
        num_nodes,
        num_edges);

    for (int i = 0; i < num_nodes; ++i)
        if (neighbor_table_offsets[i] != expected_offsets[i])
            return 1;
    for (int i = 0; i < num_edges; ++i)
        if (neighbor_table[i] != expected_neighbors[i])
            return 1;
    return 0;
}
