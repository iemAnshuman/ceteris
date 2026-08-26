/* Minimal MPI ping-pong bandwidth benchmark.
 *
 * Exists so the ceteris README can show a real measurement from a real run
 * rather than a plausible-looking one. Two ranks, one message size, report
 * bandwidth. Nothing clever.
 */
#include <mpi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    MPI_Init(&argc, &argv);

    int rank, size;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &size);
    if (size != 2) {
        if (rank == 0) fprintf(stderr, "pingpong needs exactly 2 ranks\n");
        MPI_Abort(MPI_COMM_WORLD, 1);
    }

    size_t bytes = (argc > 1) ? (size_t)atol(argv[1]) : (1u << 20);
    int iters    = (argc > 2) ? atoi(argv[2]) : 200;

    char *buf = malloc(bytes);
    memset(buf, 'x', bytes);

    /* warm up */
    for (int i = 0; i < 20; ++i) {
        if (rank == 0) {
            MPI_Send(buf, bytes, MPI_CHAR, 1, 0, MPI_COMM_WORLD);
            MPI_Recv(buf, bytes, MPI_CHAR, 1, 0, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
        } else {
            MPI_Recv(buf, bytes, MPI_CHAR, 0, 0, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
            MPI_Send(buf, bytes, MPI_CHAR, 0, 0, MPI_COMM_WORLD);
        }
    }

    MPI_Barrier(MPI_COMM_WORLD);
    double t0 = MPI_Wtime();
    for (int i = 0; i < iters; ++i) {
        if (rank == 0) {
            MPI_Send(buf, bytes, MPI_CHAR, 1, 0, MPI_COMM_WORLD);
            MPI_Recv(buf, bytes, MPI_CHAR, 1, 0, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
        } else {
            MPI_Recv(buf, bytes, MPI_CHAR, 0, 0, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
            MPI_Send(buf, bytes, MPI_CHAR, 0, 0, MPI_COMM_WORLD);
        }
    }
    double elapsed = MPI_Wtime() - t0;

    if (rank == 0) {
        double gb = (double)bytes * 2.0 * iters / 1e9;
        printf("size %zu bytes  iters %d  bandwidth %.3f GB/s\n",
               bytes, iters, gb / elapsed);
    }

    free(buf);
    MPI_Finalize();
    return 0;
}
