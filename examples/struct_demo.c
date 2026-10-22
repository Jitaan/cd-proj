struct Point { int x; int y; };

int main() {
   struct Point p;
   p.x = 3;
   p.y = 4;
   struct Point *q = &p;
   q->x = 10;
   printf("%d %d\n", p.x, p.y);
}
