"""
managed_positions 정상화 복구 스크립트
- 각 포지션을 거래소 실제 데이터로 mp 재구성
- rr >= 1이면 be_moved=True (BE 이동 완료 처리, 봇이 또 SL set 시도 안 함)
- rr < 1이면 be_moved=False (앞으로 BE 이동 가능)
- management_enabled=True (봇이 관리하도록)
- TP1 처리는 done으로 표시 (이미 chunk를 거래소에서 떼지 않으니 무시)
- runner 후보 모드로 시작 (가격이 더 가면 trailing 가능)
"""
import json
from datetime import datetime, timezone

PATH = '/home/linuxuser/bybit_bot/runtime_state.json'
NOW_ISO = datetime.now(timezone.utc).isoformat()

# 거래소에서 받은 실제 데이터 (현재 시점)
POSITIONS = {
    'AVAXUSDT': {
        'side': 'Sell',
        'qty': 251.5,
        'entry': 9.22752733,
        'sl': 9.227,
        'last': 9.155,
    },
    'DOGEUSDT': {
        'side': 'Buy',
        'qty': 31700.0,
        'entry': 0.10950003,
        'sl': 0.10697,
        'last': 0.11158,
    },
    'BNBUSDT': {
        'side': 'Sell',
        'qty': 4.94,
        'entry': 622.1,
        'sl': 629.5,
        'last': 625.6,
    },
    'SOLUSDT': {
        'side': 'Sell',
        'qty': 79.4,
        'entry': 84.78950911,
        'sl': 84.78,
        'last': 84.68,
    },
}

# 표준 TP plan (4L baseline 기준)
DEFAULT_TP_PLAN = {
    'name': 'recovered',
    'be_after_rr': 1.0,
    'trail_activate_rr': 3.0,
    'max_hold_bars': 12,
    'targets': [],   # TP1/TP2 limit order는 다시 안 깜
}


def calc_rr(side, entry, last, rpu):
    if rpu <= 0:
        return 0.0
    if side == 'Buy':
        return (last - entry) / rpu
    return (entry - last) / rpu


def main():
    with open(PATH) as f:
        s = json.load(f)
    
    mp_all = s.setdefault('managed_positions', {})
    
    print("===== 복구 시작 =====")
    
    for sym, d in POSITIONS.items():
        side = d['side']
        qty = d['qty']
        entry = d['entry']
        sl = d['sl']
        last = d['last']
        
        rpu = abs(entry - sl)
        rr = calc_rr(side, entry, last, rpu)
        
        # rr >= 1.0이면 be 이동된 상태로 간주 (SL이 entry보다 유리한 위치)
        # 단 SHORT의 경우 SL > entry는 원래 SL (BE 안 됨)
        if side == 'Buy':
            be_moved = sl >= entry  # SL이 entry 이상이면 BE 이동됨
        else:
            be_moved = sl <= entry  # SHORT은 SL이 entry 이하면 BE 이동됨
        
        # tp1_done은 be_moved와 함께 (BE 이동 후 처리됨으로 가정)
        tp1_done = be_moved
        
        # 새 mp 객체 생성
        mp_new = {
            'side': side,
            'entry_price': entry,
            'current_stop': sl,
            'risk_per_unit': rpu,
            'original_qty': qty,
            'remaining_qty_est': qty,
            'tp1_done': tp1_done,
            'be_moved': be_moved,
            'tp1_exchange_armed': False,
            'tp1_exchange_done': tp1_done,
            'tp1_exchange_order_id': '',
            'tp1_exchange_price': None,
            'tp1_exchange_qty': 0.0,
            'signal_ts': 'manual_recovered',
            'last_sync_at': NOW_ISO,
            'management_enabled': True,         # ⭐ 관리 활성화
            'tp_plan': DEFAULT_TP_PLAN,
            'tp_plan_name': 'recovered',
            'tp_targets': [],                    # TP 비활성 (이미 진행 중인 포지션)
            'runner_active': False,
            'runner_protected': False,
            'runner_candidate_2of3': False,
            'post_2of3_apply_ok': False,
            'time_exit_disabled_for_runner': False,
            'opened_at': NOW_ISO,
            'recovered_from_exchange': True,    # 표시용
        }
        
        mp_all[sym] = mp_new
        
        print(f"{sym}:")
        print(f"  side={side}, qty={qty}")
        print(f"  entry={entry}, SL={sl}, last={last}")
        print(f"  risk_per_unit={rpu:.6f}, rr={rr:.3f}")
        print(f"  be_moved={be_moved}, tp1_done={tp1_done}, management_enabled=True")
        print()
    
    # 저장
    with open(PATH, 'w') as f:
        json.dump(s, f, indent=2, default=str)
    
    print(f"===== 저장 완료 =====")
    print(f"managed_positions count: {len(mp_all)}")
    print(f"symbols: {list(mp_all.keys())}")


if __name__ == '__main__':
    main()
