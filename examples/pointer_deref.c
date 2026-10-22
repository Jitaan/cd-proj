int main() {
   int a[4];
   a[0] = 10; a[1] = 20; a[2] = 30; a[3] = 40;
   int *p;
   p = &a;
   printf("%d %d\n", *p, p[3]);
   p[0] = 99;
   printf("%d\n", a[0]);
}
