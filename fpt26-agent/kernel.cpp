void top(
    int a[10],
    int b[10],
    int c[10]
)
{
#pragma HLS PIPELINE

    for(int i=0;i<10;i++)
    {
        c[i]=a[i]+b[i];
    }
}