import asyncio
import sys
sys.path.insert(0, r'C:\Users\triya\Downloads\checker')
from checker import mass_check_with_progress

async def test():
    cards = ['5598880397218308|06|2027|740']

    async def cb(result, stats):
        print(f"Progress: done={stats['done']} live={stats['live']} dead={stats['dead']} status={result['status']}")

    print('Starting mass check...')
    results, stats = await mass_check_with_progress(cards, 99999, cb)
    print(f'Done! Results: {len(results)}, Stats: {stats}')
    for r in results:
        print(f"  {r['cc']} -> {r['status']}: {r['response']}")

asyncio.run(test())
