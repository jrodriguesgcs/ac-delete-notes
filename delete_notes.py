import asyncio
import aiohttp
import json
import os
import time
from datetime import datetime
from collections import defaultdict

# ============= CONFIGURATION FROM ENV =============
API_KEY = os.environ.get('ACTIVECAMPAIGN_API_KEY')
BASE_URL = os.environ.get('BASE_URL', 'https://globalcitizensolutions89584.api-us1.com/api/3')
TARGET_USER_ID = os.environ.get('TARGET_USER_ID', '112')
RATE_LIMIT_PER_SECOND = int(os.environ.get('RATE_LIMIT', '10'))
MAX_WORKERS = int(os.environ.get('MAX_WORKERS', '20'))
NOTES_PER_RUN = int(os.environ.get('NOTES_PER_RUN', '0'))  # 0 = unlimited
BATCH_NUMBER = int(os.environ.get('BATCH_NUMBER', '1'))

STATE_FILE = 'progress_state.json'
LOG_FILE = 'deletion_log.txt'

# ============= STATE MANAGEMENT =============

def load_state():
    """Load progress state from file"""
    default_state = {
        'processed_note_ids': [],
        'total_deleted': 0,
        'total_failed': 0,
        'batch_number': 1,
        'start_time': datetime.now().isoformat(),
        'last_run_time': None,
        'remaining_notes': 0
    }
    
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            loaded_state = json.load(f)
            # Merge with defaults to handle missing keys
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

# ============= RATE LIMITER =============

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

# ============= API FUNCTIONS =============

def get_headers():
    return {
        'Api-Token': API_KEY,
        'Content-Type': 'application/json'
    }

async def fetch_all_notes(session, rate_limiter, processed_ids):
    """Fetch all notes, excluding already processed ones"""
    log_progress(f"🔍 Fetching notes (excluding {len(processed_ids):,} already processed)...")
    
    notes = []
    offset = 0
    limit = 100
    page = 1
    start_time = time.time()
    total_seen = 0
    
    while True:
        await rate_limiter.acquire()
        url = f"{BASE_URL}/notes?limit={limit}&offset={offset}"
        
        async with session.get(url, headers=get_headers()) as response:
            if response.status != 200:
                log_progress(f"❌ Error on page {page}: HTTP {response.status}")
                break
            
            data = await response.json()
            batch = data.get('notes', [])
            
            if not batch:
                break
            
            total_seen += len(batch)
            
            # Filter: Deal notes by target user, not already processed
            filtered = [
                n for n in batch 
                if n.get('reltype') == 'Deal' 
                and n.get('userid') == TARGET_USER_ID
                and n.get('id') not in processed_ids
            ]
            
            notes.extend(filtered)
            
            if page % 10 == 0:
                log_progress(f"   Page {page:4d} | Scanned: {total_seen:6d} | Found: {len(notes):5d}")
            
            offset += limit
            page += 1
    
    elapsed = time.time() - start_time
    log_progress(f"✅ Fetched {len(notes):,} unprocessed notes in {elapsed:.1f}s")
    return notes

async def delete_note(session, rate_limiter, note_id):
    """Delete a single note"""
    await rate_limiter.acquire()
    url = f"{BASE_URL}/notes/{note_id}"
    
    async with session.delete(url, headers=get_headers()) as response:
        return {
            'note_id': note_id,
            'status': response.status,
            'success': response.status == 200
        }

async def delete_notes_batch(session, rate_limiter, note_ids, max_notes=0):
    """Delete notes in parallel with progress tracking"""
    
    # Limit notes if max_notes is set
    if max_notes > 0:
        note_ids = note_ids[:max_notes]
        log_progress(f"⚠️  Limited to {max_notes:,} notes for this run")
    
    log_progress(f"🗑️  Starting deletion of {len(note_ids):,} notes...")
    
    semaphore = asyncio.Semaphore(MAX_WORKERS)
    completed = 0
    successful = 0
    failed = 0
    start_time = time.time()
    lock = asyncio.Lock()
    last_update = 0
    
    async def bounded_delete(note_id):
        nonlocal completed, successful, failed, last_update
        
        async with semaphore:
            result = await delete_note(session, rate_limiter, note_id)
            
            async with lock:
                completed += 1
                if result['success']:
                    successful += 1
                else:
                    failed += 1
                
                current_time = time.time()
                
                # Update every 10 seconds or on failure
                if (current_time - last_update >= 10.0) or not result['success']:
                    last_update = current_time
                    elapsed = current_time - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    progress = (completed / len(note_ids)) * 100
                    eta = (len(note_ids) - completed) / rate if rate > 0 else 0
                    
                    log_progress(
                        f"   Progress: {completed:,}/{len(note_ids):,} ({progress:.1f}%) | "
                        f"✓ {successful:,} | ✗ {failed} | "
                        f"{rate:.1f}/s | ETA: {eta/60:.0f}m"
                    )
            
            return result
    
    tasks = [bounded_delete(note_id) for note_id in note_ids]
    results = await asyncio.gather(*tasks)
    
    elapsed = time.time() - start_time
    log_progress(f"✅ Completed in {elapsed:.1f}s ({elapsed/60:.1f}m)")
    
    return results

# ============= MAIN PROCESS =============

async def main():
    log_progress("=" * 80)
    log_progress(f"🚀 ACTIVECAMPAIGN NOTE DELETION - BATCH #{BATCH_NUMBER}")
    log_progress("=" * 80)
    log_progress(f"Rate Limit: {RATE_LIMIT_PER_SECOND} req/s")
    log_progress(f"Workers: {MAX_WORKERS}")
    log_progress(f"Max notes this run: {'Unlimited' if NOTES_PER_RUN == 0 else f'{NOTES_PER_RUN:,}'}")
    log_progress("")
    
    # Load state
    state = load_state()
    log_progress(f"📊 Previous Progress:")
    log_progress(f"   Total deleted: {state['total_deleted']:,}")
    log_progress(f"   Total failed: {state['total_failed']:,}")
    log_progress(f"   Already processed: {len(state['processed_note_ids']):,}")
    log_progress("")
    
    rate_limiter = RateLimiter(max_per_second=RATE_LIMIT_PER_SECOND)
    start_time = time.time()
    
    async with aiohttp.ClientSession() as session:
        # Fetch remaining notes
        notes = await fetch_all_notes(session, rate_limiter, set(state['processed_note_ids']))
        
        if not notes:
            log_progress("🎉 NO MORE NOTES TO DELETE! Job complete!")
            state['remaining_notes'] = 0
            save_state(state)
            return
        
        note_ids = [n['id'] for n in notes]
        log_progress("")
        log_progress(f"📋 Found {len(note_ids):,} notes to delete")
        
        # Delete notes
        results = await delete_notes_batch(session, rate_limiter, note_ids, NOTES_PER_RUN)
        
        # Update state
        successful = sum(1 for r in results if r['success'])
        failed = sum(1 for r in results if not r['success'])
        
        state['total_deleted'] += successful
        state['total_failed'] += failed
        state['processed_note_ids'].extend([r['note_id'] for r in results])
        state['batch_number'] = BATCH_NUMBER
        
        # Calculate remaining
        remaining_estimate = len(notes) - len(results) if NOTES_PER_RUN > 0 else 0
        state['remaining_notes'] = remaining_estimate
        
        save_state(state)
        
        # Final summary
        elapsed = time.time() - start_time
        log_progress("")
        log_progress("=" * 80)
        log_progress("📊 BATCH SUMMARY")
        log_progress("=" * 80)
        log_progress(f"✅ Deleted this run: {successful:,}")
        log_progress(f"❌ Failed this run: {failed}")
        log_progress(f"⏱️  Run time: {elapsed/60:.1f} minutes")
        log_progress(f"📈 Deletion rate: {len(results)/elapsed:.2f} notes/s")
        log_progress("")
        log_progress("📊 OVERALL PROGRESS")
        log_progress("=" * 80)
        log_progress(f"✅ Total deleted: {state['total_deleted']:,}")
        log_progress(f"❌ Total failed: {state['total_failed']:,}")
        log_progress(f"📊 API calls this run: {rate_limiter.request_count:,}")
        
        if NOTES_PER_RUN > 0:
            log_progress(f"⏭️  Estimated remaining: {remaining_estimate:,}+ notes")
            log_progress(f"🔄 Next batch will continue automatically")
        
        log_progress("=" * 80)

if __name__ == "__main__":
    if not API_KEY:
        print("❌ ERROR: ACTIVECAMPAIGN_API_KEY environment variable not set!")
        exit(1)
    
    asyncio.run(main())
