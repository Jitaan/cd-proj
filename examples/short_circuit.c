int main() {
  int a = 0;
  int b = 5;
  if (a && (b / a > 1)) {
    printf("%d\n", 1);
  } else {
    printf("%d\n", 0);
  }
  if (b || (1 / 0 != 0)) {
    printf("%d\n", 2);
  } else {
    printf("%d\n", 3);
  }
  printf("%d\n", a);
}
