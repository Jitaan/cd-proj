int main() {
   int a[5];
   for (int i = 0; i < 5; i++) { a[i] = i + 1; }
   int *p = &a;
   /* walk with index instead */
   int s = 0;
   for (int i = 0; i < 5; i++) {
      s = s + p[i];
   }
   printf("%d\n", s);
}
