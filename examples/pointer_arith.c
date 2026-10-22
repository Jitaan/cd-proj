int main() {
   int a[4];
   a[0] = 10; a[1] = 20; a[2] = 30; a[3] = 40;
   int *p = a;
   int s = 0;
   for (int i = 0; i < 4; i++) {
      s = s + *p;
      p++;
   }
   printf("%d\n", s);
   printf("%d\n", p - a);
}
