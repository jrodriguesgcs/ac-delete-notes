import asyncio
import aiohttp
import json
import os
import time
from datetime import datetime

# ============= CONFIGURATION FROM ENV =============
API_KEY = os.environ.get('ACTIVECAMPAIGN_API_KEY')
BASE_URL = os.environ.get('BASE_URL', 'https://globalcitizensolutions89584.api-us1.com/api/3')
TARGET_USER_ID = os.environ.get('TARGET_USER_ID', '112')
RATE_LIMIT_PER_SECOND = int(os.environ.get('RATE_LIMIT', '10'))
MAX_WORKERS = int(os.environ.get('MAX_WORKERS', '20'))
NOTES_PER_RUN = int(os.environ.get('NOTES_PER_RUN', '0'))
BATCH_NUMBER = int(os.environ.get('BATCH_NUMBER', '1'))

STATE_FILE = 'progress_state.json'
LOG_FILE = 'deletion_log.txt'

# ============= OPTIMIZED APPROACH =============
# NEW STRATEGY:
# 1. Fetch all deals (~750 API calls for 75k deals)
# 2. For each deal, fetch notes and filter by user 112
# 3. Delete matching notes
# 
# This SKIPS fetching 640k+ contact notes entirely!
# Saves ~59k API calls vs old approach
# =============================================

def get_headers():
    return {
        'Api-Token': API_KEY,
        'Content-Type': 'application/json'
    }

def load_state():
    """Load progress state from file"""
    default_state = {
        'processed_deal_ids': [],
        'deleted_note_ids': [],
        'total_deleted': 0,
        'total_failed': 0,
        'batch_number': 1,
        'start_time': datetime.now().isoformat(),
        'last_run_time': None,
        'remaining_deals': 0
    }
    
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            loaded_state = json.load(f)
            for key, value in default_state.items():
                if key not in loaded_state:
                    loaded_state[key] = value
            return loaded_state
    
    return default_state

def save_state(state):
    """Save progress state to file"""
    state['last_run_time'] = datetime.now().isoformat()
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def log_progress(message):
    """Log progress to file and stdout"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_msg = f"[{timestamp}] {message}"
    print(log_msg)
    with open(LOG_FILE, 'a') as f:
        f.write(log_msg + '\n')

class RateLimiter:
    def __init__(self, max_per_second=10):
        self.max_per_second = max_per_second
        self.requests = []
        self.lock = asyncio.Lock()
        self.request_count = 0
    
    async def acquire(self):
        async with self.lock:
            now = time.time()
            self.requests = [req_time for req_time in self.requests if now - req_time < 1.0]
            
            if len(self.requests) >= self.max_per_second:
                sleep_time = 1.0 - (now - self.requests[0])
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                    now = time.time()
                    self.requests = [req_time for req_time in self.requests if now - req_time < 1.0]
            
            self.requests.append(now)
            self.request_count += 1

async def fetch_all_deals(session, rate_limiter, processed_deal_ids):
    """Fetch all deals, excluding already processed ones"""
    log_progress("📋 Step 1: Fetching all DEALS...")
    
    deals = []
    offset = 0
    limit = 100
    page = 1
    start_time = time.time()
    
    while True:
        await rate_limiter.acquire()
        url = f"{BASE_URL}/deals?limit={limit}&offset={offset}"
        
        try:
            timeout = aiohttp.ClientTimeout(total=60)
            async with session.get(url, headers=get_headers(), timeout=timeout) as response:
                if response.status != 200:
                    log_progress(f"❌ Error fetching deals: HTTP {response.status}")
                    break
                
                data = await response.json()
                batch = data.get('deals', [])
                
                if not batch:
                    break
                
                # Filter out already processed deals
                new_deals = [d for d in batch if d['id'] not in processed_deal_ids]
                deals.extend(new_deals)
                
                if page % 10 == 0:
                    log_progress(f"   Page {page:4d} | Total deals: {len(deals):6d} | Already processed: {len(processed_deal_ids):6d}")
                
                offset += limit
                page += 1
                
        except Exception as e:
            log_progress(f"❌ Error: {str(e)}")
            break
    
    elapsed = time.time() - start_time
    log_progress(f"✅ Fetched {len(deals):,} unprocessed deals in {elapsed:.1f}s")
    return deals

async def fetch_deal_notes(session, rate_limiter, deal_id):
    """Fetch notes for a specific deal and filter by user ID"""
    await rate_limiter.acquire()
    url = f"{BASE_URL}/deals/{deal_id}/notes"
    
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with session.get(url, headers=get_headers(), timeout=timeout) as response:
            if response.status != 200:
                return {'deal_id': deal_id, 'notes': [], 'all_notes': 0, 'user_notes': 0}
            
            data = await response.json()
            all_notes = data.get('notes', [])
            
            # Count notes by different users for verification
            notes_by_user = {}
            for note in all_notes:
                user_id = note.get('userid', 'unknown')
                notes_by_user[user_id] = notes_by_user.get(user_id, 0) + 1
            
            # Filter ONLY for notes by target user
            filtered = [n for n in all_notes if n.get('userid') == TARGET_USER_ID]
            
            return {
                'deal_id': deal_id,
                'notes': filtered,
                'all_notes': len(all_notes),
                'user_notes': len(filtered),
                'notes_by_user': notes_by_user
            }
            
    except Exception as e:
        log_progress(f"⚠️  Error fetching notes for deal {deal_id}: {str(e)}")
        return {'deal_id': deal_id, 'notes': [], 'all_notes': 0, 'user_notes': 0}

async def delete_note(session, rate_limiter, note_id):
    """Delete a single note with retry logic"""
    await rate_limiter.acquire()
    url = f"{BASE_URL}/notes/{note_id}"
    
    max_retries = 3
    for retry in range(max_retries):
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with session.delete(url, headers=get_headers(), timeout=timeout) as response:
                return {
                    'note_id': note_id,
                    'status': response.status,
                    'success': response.status == 200
                }
        except asyncio.TimeoutError:
            if retry < max_retries - 1:
                await asyncio.sleep(2)
            else:
                return {'note_id': note_id, 'status': 'timeout', 'success': False}
        except Exception as e:
            if retry < max_retries - 1:
                await asyncio.sleep(2)
            else:
                return {'note_id': note_id, 'status': f'error', 'success': False}

async def process_deal(session, rate_limiter, deal_id, state, lock):
    """Process a single deal: fetch notes, delete if by user 112"""
    notes = await fetch_deal_notes(session, rate_limiter, deal_id)
    
    results = []
    for note in notes:
        result = await delete_note(session, rate_limiter, note['id'])
        results.append(result)
    
    async with lock:
        state['processed_deal_ids'].append(deal_id)
        for result in results:
            if result['success']:
                state['total_deleted'] += 1
                state['deleted_note_ids'].append(result['note_id'])
            else:
                state['total_failed'] += 1
    
    return {
        'deal_id': deal_id,
        'notes_found': len(notes),
        'notes_deleted': sum(1 for r in results if r['success']),
        'notes_failed': sum(1 for r in results if not r['success'])
    }

async def main():
    log_progress("=" * 80)
    log_progress(f"🚀 OPTIMIZED DEAL NOTES DELETION - BATCH #{BATCH_NUMBER}")
    log_progress("=" * 80)
    log_progress(f"⚡ NEW APPROACH: Fetch deals first, then their notes")
    log_progress(f"✅ BENEFIT: Skips all contact notes (saves ~60k API calls!)")
    log_progress(f"📋 Target: Deal notes by user {TARGET_USER_ID}")
    log_progress(f"Rate Limit: {RATE_LIMIT_PER_SECOND} req/s")
    log_progress(f"Workers: {MAX_WORKERS}")
    log_progress("")
    
    state = load_state()
    log_progress(f"📊 Previous Progress:")
    log_progress(f"   Deals processed: {len(state['processed_deal_ids']):,}")
    log_progress(f"   Notes deleted: {state['total_deleted']:,}")
    log_progress(f"   Notes failed: {state['total_failed']:,}")
    log_progress("")
    
    rate_limiter = RateLimiter(max_per_second=RATE_LIMIT_PER_SECOND)
    start_time = time.time()
    
    async with aiohttp.ClientSession() as session:
        # Step 1: Fetch all unprocessed deals
        deals = await fetch_all_deals(session, rate_limiter, set(state['processed_deal_ids']))
        
        if not deals:
            log_progress("")
            log_progress("🎉 ALL DEALS PROCESSED! No more deal notes to delete.")
            log_progress(f"✅ Total deleted: {state['total_deleted']:,} notes")
            state['remaining_deals'] = 0
            save_state(state)
            return
        
        log_progress("")
        log_progress(f"📋 Step 2: Processing {len(deals):,} deals (fetching & deleting notes)...")
        log_progress(f"⏱️  Estimated time: {len(deals) * 2 / RATE_LIMIT_PER_SECOND / 60:.0f} minutes")
        log_progress("")
        
        # Step 2: Process deals in parallel
        semaphore = asyncio.Semaphore(MAX_WORKERS)
        lock = asyncio.Lock()
        completed = 0
        last_update = 0
        deals_with_notes = 0
        
        async def bounded_process(deal_id):
            nonlocal completed, last_update, deals_with_notes
            
            async with semaphore:
                result = await process_deal(session, rate_limiter, deal_id, state, lock)
                
                completed += 1
                if result['notes_found'] > 0:
                    deals_with_notes += 1
                
                current_time = time.time()
                if current_time - last_update >= 10.0:
                    last_update = current_time
                    elapsed = current_time - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    progress = (completed / len(deals)) * 100
                    eta = (len(deals) - completed) / rate if rate > 0 else 0
                    
                    log_progress(
                        f"   Progress: {completed:,}/{len(deals):,} ({progress:.1f}%) | "
                        f"Deals w/notes: {deals_with_notes:,} | "
                        f"Deleted: {state['total_deleted']:,} | "
                        f"Rate: {rate:.1f} deals/s | ETA: {eta/60:.0f}m"
                    )
                    
                    # Save state periodically
                    if completed % 100 == 0:
                        save_state(state)
                
                return result
        
        # Limit deals processed if NOTES_PER_RUN is set
        deals_to_process = deals
        if NOTES_PER_RUN > 0:
            # Estimate deals needed based on avg 70 notes per deal
            estimated_deals = NOTES_PER_RUN // 70 + 10
            deals_to_process = deals[:estimated_deals]
            log_progress(f"⚠️  Limited to ~{len(deals_to_process):,} deals for this run")
        
        tasks = [bounded_process(deal['id']) for deal in deals_to_process]
        await asyncio.gather(*tasks)
        
        # Final save
        state['batch_number'] = BATCH_NUMBER
        state['remaining_deals'] = len(deals) - len(deals_to_process)
        save_state(state)
        
        # Summary
        elapsed = time.time() - start_time
        log_progress("")
        log_progress("=" * 80)
        log_progress("📊 BATCH COMPLETE")
        log_progress("=" * 80)
        log_progress(f"✅ Deals processed: {completed:,}")
        log_progress(f"✅ Deals with notes by user {TARGET_USER_ID}: {deals_with_notes:,}")
        log_progress(f"✅ Notes deleted this run: {state['total_deleted'] - (state['total_deleted'] - deals_with_notes):,}")
        log_progress(f"⏱️  Time: {elapsed/60:.1f} minutes")
        log_progress(f"📈 Rate: {completed/elapsed:.2f} deals/s")
        log_progress("")
        log_progress("📊 OVERALL PROGRESS")
        log_progress("=" * 80)
        log_progress(f"✅ Total deals processed: {len(state['processed_deal_ids']):,}")
        log_progress(f"✅ Total notes deleted: {state['total_deleted']:,}")
        log_progress(f"❌ Total failed: {state['total_failed']:,}")
        log_progress(f"📊 API calls: {rate_limiter.request_count:,}")
        log_progress(f"⏭️  Remaining deals: {state['remaining_deals']:,}")
        log_progress("=" * 80)

if __name__ == "__main__":
    if not API_KEY:
        print("❌ ERROR: ACTIVECAMPAIGN_API_KEY not set!")
        exit(1)
    
    asyncio.run(main())
