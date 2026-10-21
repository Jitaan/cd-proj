int main() {
    int a = 5;
    int b = a + 2;
    int c = b * 3;
    int d = c * 2;
    int e = a + 2;  // CSE opportunity
    int f = 10 * 4; // Constant folding
    int g = d / 2;  // Strength reduction
    int h = d % 4;  // Strength reduction
    printf("%d %d %d %d %d %d %d %d\n", a, b, c, d, e, f, g, h);
    return 0;
}