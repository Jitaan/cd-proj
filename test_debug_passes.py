import sys, os
sys.path.insert(0, r'C:\data\cd-proj\backend')
import passes
import service

print('passes.ADVISED:', passes.ADVISED)

src = 'int main() { int x = 5; int y = 3; int z; if (x > y) { z = x; } else { z = y; } printf("%d\\n", z); return 0; }'
result = service.run_pipeline(src, mode='all', lang='c')
print('passes_run:', result['passes_run'])
print('len:', len(result['passes_run']))