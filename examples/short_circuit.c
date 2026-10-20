int main() {
  int a = 0;
  int b = 5;
  if (a && (b / a > 1)) {
    print(1);
  } else {
    print(0);
  }
  if (b || (1 / 0 != 0)) {
    print(2);
  } else {
    print(3);
  }
  print(a);
}
