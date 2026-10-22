"""Regression tests for pointers and struct member access.

Covers pointers to scalars, pointer arithmetic (+, -, ++/--, difference),
and `struct`/`union` member access (`.` and `->`).  Every program is run in
all optimiser modes: the optimiser must never change observable output, and in
particular must not propagate a value across a store through an aliasing
pointer.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

import service  # noqa: E402


PROGRAMS = {
    # -- pointers to scalars ----------------------------------------
    "scalar_read": ("""
int main(){
   int x = 41;
   int *p = &x;
   printf("%d\\n", *p);
}
""", "41\n"),

    "scalar_write": ("""
int main(){
   int x = 41;
   int *p = &x;
   *p = *p + 1;
   printf("%d\\n", x);
}
""", "42\n"),

    "scalar_split_decl": ("""
int main(){
   int x = 7;
   int *p;
   p = &x;
   printf("%d\\n", *p);
}
""", "7\n"),

    "swap_fn": ("""
void sw(int *a, int *b){
   int t = *a;
   *a = *b;
   *b = t;
}
int main(){
   int x = 1;
   int y = 2;
   sw(&x, &y);
   printf("%d %d\\n", x, y);
}
""", "2 1\n"),

    # -- pointer arithmetic -----------------------------------------
    "arith_add": ("""
int main(){
   int a[5];
   for (int i = 0; i < 5; i++) { a[i] = i + 1; }
   int *p = a;
   int s = 0;
   for (int i = 0; i < 5; i++) { s = s + *(p + i); }
   printf("%d\\n", s);
}
""", "15\n"),

    "arith_incr": ("""
int main(){
   int a[4];
   a[0]=10; a[1]=20; a[2]=30; a[3]=40;
   int *p = a;
   int s = 0;
   for (int i = 0; i < 4; i++) { s = s + *p; p++; }
   printf("%d\\n", s);
}
""", "100\n"),

    "arith_decr": ("""
int main(){
   int a[4];
   a[0]=1; a[1]=2; a[2]=3; a[3]=4;
   int *p = &a[3];
   int s = 0;
   for (int i = 0; i < 4; i++) { s = s + *p; p--; }
   printf("%d\\n", s);
}
""", "10\n"),

    "arith_sub": ("""
int main(){
   int a[8];
   for (int i = 0; i < 8; i++) { a[i] = i * 10; }
   int *p = &a[6];
   printf("%d\\n", *(p - 4));
}
""", "20\n"),

    "ptrdiff": ("""
int main(){
   int a[10];
   int *p = &a[2];
   int *q = &a[7];
   printf("%d\\n", q - p);
}
""", "5\n"),

    "ptr_compare": ("""
int main(){
   int a[5];
   int *p = &a[1];
   int *q = &a[4];
   if (p < q) { printf("lt\\n"); } else { printf("ge\\n"); }
}
""", "lt\n"),

    "ptr_index": ("""
int main(){
   int a[5];
   for (int i = 0; i < 5; i++) { a[i] = i + 1; }
   int *p = a;
   int s = 0;
   for (int i = 0; i < 5; i++) { s = s + p[i]; }
   printf("%d\\n", s);
}
""", "15\n"),

    "store_through_ptr_index": ("""
int main(){
   int a[3];
   a[0]=1; a[1]=2; a[2]=3;
   int *p = a;
   p[1] = 20;
   printf("%d\\n", a[1]);
}
""", "20\n"),

    "compound_through_ptr": ("""
int main(){
   int x = 5;
   int *p = &x;
   *p += 10;
   printf("%d\\n", x);
}
""", "15\n"),

    "addr_of_element": ("""
int main(){
   int a[4];
   a[0]=1; a[1]=2; a[2]=3; a[3]=4;
   int *p = &a[2];
   printf("%d\\n", *p);
}
""", "3\n"),

    "pointer_to_pointer": ("""
int main(){
   int x = 5;
   int *p = &x;
   int **pp = &p;
   **pp = 9;
   printf("%d\\n", x);
}
""", "9\n"),

    # -- struct member access ---------------------------------------
    "struct_basic": ("""
struct P { int x; int y; };
int main(){
   struct P p;
   p.x = 3;
   p.y = 4;
   printf("%d\\n", p.x + p.y);
}
""", "7\n"),

    "struct_pointer": ("""
struct P { int x; int y; };
int main(){
   struct P p;
   p.x = 3;
   p.y = 4;
   struct P *q = &p;
   q->x = 5;
   printf("%d\\n", p.x + p.y);
}
""", "9\n"),

    "struct_nested": ("""
struct Inner { int a; int b; };
struct Outer { struct Inner in; int c; };
int main(){
   struct Outer o;
   o.in.a = 1;
   o.in.b = 2;
   o.c = 3;
   printf("%d\\n", o.in.a + o.in.b + o.c);
}
""", "6\n"),

    "struct_pointer_member": ("""
struct Box { int v; int *at; };
int main(){
   int arr[3];
   arr[0]=7; arr[1]=8; arr[2]=9;
   struct Box b;
   b.v = 100;
   b.at = arr;
   printf("%d\\n", b.v + b.at[2]);
}
""", "109\n"),

    "array_of_structs": ("""
struct P { int x; int y; };
int main(){
   struct P a[3];
   for (int i = 0; i < 3; i++) { a[i].x = i; a[i].y = i * 2; }
   int s = 0;
   for (int i = 0; i < 3; i++) { s = s + a[i].x + a[i].y; }
   printf("%d\\n", s);
}
""", "9\n"),

    "struct_padding": ("""
struct S { char c; int i; };
int main(){
   struct S s;
   s.c = 65;
   s.i = 1000;
   printf("%d %d\\n", s.c, s.i);
}
""", "65 1000\n"),

    "struct_assign": ("""
struct P { int x; int y; };
int main(){
   struct P a;
   a.x = 1; a.y = 2;
   struct P b;
   b = a;
   b.x = 9;
   printf("%d %d\\n", a.x, b.x);
}
""", "1 9\n"),

    "struct_via_pointer_arith": ("""
struct P { int x; };
int main(){
   struct P a[3];
   a[0].x = 10; a[1].x = 20; a[2].x = 30;
   struct P *p = a;
   printf("%d\\n", (p + 2)->x);
}
""", "30\n"),

    "struct_init_list": ("""
struct P { int x; int y; };
int main(){
   struct P p = {4, 5};
   printf("%d\\n", p.x + p.y);
}
""", "9\n"),

    "global_struct": ("""
struct P { int x; int y; };
struct P g;
int main(){
   g.x = 2;
   g.y = 3;
   printf("%d\\n", g.x + g.y);
}
""", "5\n"),

    "union_shared_storage": ("""
union U { int i; int j; };
int main(){
   union U u;
   u.i = 7;
   printf("%d\\n", u.j);
}
""", "7\n"),

    # -- aliasing safety (optimiser must not fold across *p stores) --
    "alias_store": ("""
int main(){
   int x = 5;
   int *p = &x;
   *p = 7;
   printf("%d\\n", x);
}
""", "7\n"),

    "alias_prop": ("""
int main(){
   int x = 5;
   int *p = &x;
   int y = x;
   *p = 9;
   printf("%d %d\\n", x, y);
}
""", "9 5\n"),

    "alias_cond": ("""
int main(){
   int x = 0;
   int *p = &x;
   *p = 3;
   if (x == 3) { printf("yes\\n"); } else { printf("no %d\\n", x); }
}
""", "yes\n"),
}


@pytest.mark.parametrize("name", sorted(PROGRAMS))
@pytest.mark.parametrize("mode", ["none", "ai", "all"])
def test_optimiser_preserves_pointer_output(name, mode):
    source, expected = PROGRAMS[name]
    result = service.run_pipeline(source, mode=mode, lang="c")

    assert result["error"] is None, result["error"]
    assert result["output_before"] == [expected]
    assert result["output_after"] == [expected]
    assert result["match"] is True
