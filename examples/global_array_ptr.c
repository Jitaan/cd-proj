int g[6];
int main() {
   for (int i = 0; i < 6; i++) {
      g[i] = i * 2;
   }
   int *p = &g;
   int s = 0;
   for (int i = 0; i < 6; i++) {
      s = s + p[i];
   }
   printf("%d\n", s);
}
