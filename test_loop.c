int main() {
    int sum = 0;
    for (int i = 1; i <= 10; i = i + 1) {
        int x = i * 2;
        int y = x + 5;
        sum = sum + y;
    }
    printf("%d\n", sum);
    return 0;
}