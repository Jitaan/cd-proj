int main() {
  int x = 2;
  int y = 3;
  int a = x*y + 1;
  int b = x*y + 1;
  int c = a + b;
  if (c > 5) {
    c = c / 2;
  } else {
    c = c * 2;
  }
  int i;
  for (i = 0; i < 3; i++) {
    c += i;
  }
  printf("%d\n", c);
}
