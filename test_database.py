#!/usr/bin/env python3
"""
Test script to check MariaDB database connection and status for VCK Online
"""

import sys

def test_database_connection():
    """Test the database connection and basic functionality"""
    
    # Database connection parameters from game.py
    # Using localhost for SSH port forwarding (ssh -L 3306:localhost:3306 lukesau.com)
    db_config = {
        'user': 'vckonline',
        'password': 'vckonline',
        'host': '127.0.0.1',
        'database': 'vckonline'
    }
    
    print("Testing VCK Online Database Connection")
    print("=" * 50)
    
    # Test 1: Check if mariadb module is available
    print("\n1. Checking mariadb module...")
    try:
        import mariadb
        print("   ✓ mariadb module found")
    except ImportError:
        print("   ✗ mariadb module not found")
        print("   Install with: pip install mariadb")
        print("   Or with user flag: pip install --user mariadb")
        print("   Or use virtualenv: python3 -m venv .env && source .env/bin/activate && pip install mariadb")
        return False
    
    # Test 1.5: Check if database server is accessible
    print("\n1.5. Checking if database server is accessible on localhost:3306...")
    print("   (Make sure SSH port forwarding is active: ssh -L 3306:localhost:3306 lukesau.com)")
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    result = sock.connect_ex(('127.0.0.1', 3306))
    sock.close()
    if result == 0:
        print("   ✓ Database server is accessible on localhost:3306")
    else:
        print("   ✗ Cannot reach localhost:3306")
        print("\n   Make sure SSH port forwarding is active:")
        print("   ssh -L 3306:localhost:3306 lukesau.com")
        return False
    
    # Test 2: Test connection
    print("\n2. Testing database connection...")
    try:
        connection = mariadb.connect(**db_config)
        print(f"   ✓ Successfully connected to database '{db_config['database']}'")
        cursor = connection.cursor(dictionary=True)
    except mariadb.Error as e:
        print(f"   ✗ Connection failed: {e}")
        print("\n   Possible issues:")
        print("   - Database 'vckonline' does not exist")
        print("   - User 'vckonline' does not exist or password is incorrect")
        print("   - User does not have permission to access from this IP")
        return False
    
    # Test 3: Check if required tables exist
    print("\n3. Checking required tables...")
    required_tables = ['citizens', 'monsters', 'domains', 'dukes', 'starters']
    existing_tables = []
    
    try:
        cursor.execute("SHOW TABLES")
        # SHOW TABLES returns a dict with key like 'Tables_in_vckonline'
        tables = [list(row.values())[0] for row in cursor.fetchall()]
        
        for table in required_tables:
            if table in tables:
                print(f"   ✓ Table '{table}' exists")
                existing_tables.append(table)
            else:
                print(f"   ✗ Table '{table}' is missing")
    except mariadb.Error as e:
        print(f"   ✗ Error checking tables: {e}")
        connection.close()
        return False
    
    # Test 4: Check table row counts
    print("\n4. Checking table data...")
    for table in existing_tables:
        try:
            cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
            count = cursor.fetchone()['count']
            print(f"   {table}: {count} rows")
        except mariadb.Error as e:
            print(f"   ✗ Error counting rows in '{table}': {e}")
    
    # Test 4.5: Display all card data
    print("\n4.5. Displaying all card data...")
    
    # Citizens
    try:
        cursor.execute("SELECT name, gold_cost, roll_match1, roll_match2, shadow_count, holy_count, soldier_count, worker_count, expansion FROM citizens ORDER BY expansion, roll_match1")
        citizens = cursor.fetchall()
        print(f"\n   CITIZENS ({len(citizens)} total):")
        for c in citizens:
            name, gc, r1, r2, sh, ho, so, wo, exp = c
            roles = []
            if sh: roles.append(f"{sh} Shadow")
            if ho: roles.append(f"{ho} Holy")
            if so: roles.append(f"{so} Soldier")
            if wo: roles.append(f"{wo} Worker")
            role_str = ", ".join(roles) if roles else "No roles"
            roll_str = f"{r1}" + (f"/{r2}" if r2 else "")
            print(f"      {name:20} | Cost: {gc:2}gp | Roll: {roll_str:5} | {role_str:20} | {exp}")
    except mariadb.Error as e:
        print(f"   ✗ Error fetching citizens: {e}")
    
    # Monsters
    try:
        cursor.execute("SELECT name, area, monster_type, monster_order, strength_cost, magic_cost, vp_reward, gold_reward, strength_reward, magic_reward, expansion FROM monsters ORDER BY area, monster_order")
        monsters = cursor.fetchall()
        print(f"\n   MONSTERS ({len(monsters)} total):")
        for m in monsters:
            name, area, mtype, order, sc, mc, vp, gr, sr, mr, exp = m
            cost_str = f"{sc}sp" + (f" + {mc}mp" if mc else "")
            reward_str = f"{vp}vp" + (f" + {gr}gp" if gr else "") + (f" + {sr}sp" if sr else "") + (f" + {mr}mp" if mr else "")
            print(f"      {name:25} | {area:10} | {mtype:8} | Cost: {cost_str:10} | Reward: {reward_str:15} | {exp}")
    except mariadb.Error as e:
        print(f"   ✗ Error fetching monsters: {e}")
    
    # Domains
    try:
        cursor.execute("SELECT name, gold_cost, shadow_count, holy_count, soldier_count, worker_count, vp_reward, text, expansion FROM domains ORDER BY expansion, gold_cost")
        domains = cursor.fetchall()
        print(f"\n   DOMAINS ({len(domains)} total):")
        for d in domains:
            name, gc, sh, ho, so, wo, vp, text, exp = d
            roles = []
            if sh: roles.append(f"{sh} Shadow")
            if ho: roles.append(f"{ho} Holy")
            if so: roles.append(f"{so} Soldier")
            if wo: roles.append(f"{wo} Worker")
            role_str = ", ".join(roles) if roles else "No roles"
            text_preview = (text[:40] + "...") if text and len(text) > 40 else (text or "No effect")
            print(f"      {name:25} | Cost: {gc:2}gp | {role_str:20} | {vp}vp | {text_preview} | {exp}")
    except mariadb.Error as e:
        print(f"   ✗ Error fetching domains: {e}")
    
    # Dukes
    try:
        cursor.execute("SELECT name, gold_mult, strength_mult, magic_mult, shadow_mult, holy_mult, soldier_mult, worker_mult, monster_mult, citizen_mult, domain_mult, expansion FROM dukes ORDER BY expansion, name")
        dukes = cursor.fetchall()
        print(f"\n   DUKES ({len(dukes)} total):")
        for d in dukes:
            name, gm, sm, mm, shm, hom, som, wom, mom, cm, dom, exp = d
            mults = []
            if gm: mults.append(f"Gold×{gm}")
            if sm: mults.append(f"Str×{sm}")
            if mm: mults.append(f"Mag×{mm}")
            if shm: mults.append(f"Shadow×{shm}")
            if hom: mults.append(f"Holy×{hom}")
            if som: mults.append(f"Soldier×{som}")
            if wom: mults.append(f"Worker×{wom}")
            if mom: mults.append(f"Monster×{mom}")
            if cm: mults.append(f"Citizen×{cm}")
            if dom: mults.append(f"Domain×{dom}")
            mult_str = ", ".join(mults) if mults else "No multipliers"
            print(f"      {name:30} | {mult_str} | {exp}")
    except mariadb.Error as e:
        print(f"   ✗ Error fetching dukes: {e}")
    
    # Starters
    try:
        cursor.execute("SELECT name, roll_match1, roll_match2, gold_payout_on_turn, gold_payout_off_turn, strength_payout_on_turn, strength_payout_off_turn, magic_payout_on_turn, magic_payout_off_turn, expansion FROM starters ORDER BY roll_match1")
        starters = cursor.fetchall()
        print(f"\n   STARTERS ({len(starters)} total):")
        for s in starters:
            name, r1, r2, gpot, gpoff, spot, spoff, mpot, mpoff, exp = s
            roll_str = f"{r1}" + (f"/{r2}" if r2 else "")
            payouts = []
            if gpot: payouts.append(f"{gpot}gp (on)")
            if gpoff: payouts.append(f"{gpoff}gp (off)")
            if spot: payouts.append(f"{spot}sp (on)")
            if spoff: payouts.append(f"{spoff}sp (off)")
            if mpot: payouts.append(f"{mpot}mp (on)")
            if mpoff: payouts.append(f"{mpoff}mp (off)")
            payout_str = ", ".join(payouts) if payouts else "No payouts"
            print(f"      {name:20} | Roll: {roll_str:5} | {payout_str} | {exp}")
    except mariadb.Error as e:
        print(f"   ✗ Error fetching starters: {e}")
    
    # Test 5: Test stored procedures
    print("\n5. Checking stored procedures...")
    print("   (These are helper functions used by the game code to select cards)")
    required_procedures = [
        'select_base1_citizens',
        'select_base1_monsters',
        'select_base2_citizens',
        'select_base2_monsters',
        'select_random_domains',
        'select_random_dukes'
    ]
    
    try:
        cursor.execute("SHOW PROCEDURE STATUS WHERE Db = 'vckonline'")
        procedures = [row['Name'] for row in cursor.fetchall()]
        
        missing_procedures = []
        for proc in required_procedures:
            if proc in procedures:
                print(f"   ✓ Procedure '{proc}' exists")
            else:
                print(f"   ✗ Procedure '{proc}' is missing")
                missing_procedures.append(proc)
        
        if missing_procedures:
            print(f"\n   Note: {len(missing_procedures)} stored procedures are missing.")
            print("   These can be created from the SQL files in the sql/ directory:")
            print("   - select_base1_citizens_sp.sql")
            print("   - select_base1_monsters_sp.sql")
            print("   - select_base2_citizens_sp.sql")
            print("   - select_base2_monsters_sp.sql")
            print("   - select_random_domains_sp.sql")
            print("   - select_random_dukes_sp.sql")
    except mariadb.Error as e:
        print(f"   ✗ Error checking procedures: {e}")
    
    # Test 6: Test a sample query
    print("\n6. Testing sample query...")
    try:
        cursor.execute("SELECT * FROM starters LIMIT 1")
        result = cursor.fetchone()
        if result:
            name = result.get('name', 'N/A')
            print(f"   ✓ Sample query successful (found starter: {name})")
        else:
            print("   ⚠ Sample query returned no results (table may be empty)")
    except mariadb.Error as e:
        print(f"   ✗ Sample query failed: {e}")
    
    # Test 7: Test all stored procedures and display results
    print("\n7. Testing stored procedures and displaying results...")
    
    # Get list of available procedures
    try:
        cursor.execute("SHOW PROCEDURE STATUS WHERE Db = 'vckonline'")
        available_procedures = {row['Name']: True for row in cursor.fetchall()}
    except mariadb.Error as e:
        print(f"   ✗ Error checking procedures: {e}")
        available_procedures = {}
    
    # Test each procedure
    procedure_tests = [
        ('select_base1_citizens', 'Citizens'),
        ('select_base1_monsters', 'Monsters'),
        ('select_base2_citizens', 'Citizens'),
        ('select_base2_monsters', 'Monsters'),
        ('select_random_domains', 'Domains'),
        ('select_random_dukes', 'Dukes')
    ]
    
    for proc_name, card_type in procedure_tests:
        if proc_name not in available_procedures:
            print(f"\n   ✗ {proc_name} - Procedure not found (skipping)")
            continue
        
        try:
            print(f"\n   Testing {proc_name}():")
            cursor.callproc(proc_name)
            results = cursor.fetchall()
            
            if not results:
                print(f"      ⚠ No results returned")
                continue
            
            print(f"      ✓ Returned {len(results)} {card_type.lower()}")
            
            # Display results based on card type (using dictionary access)
            if card_type == 'Citizens':
                print(f"      {card_type} returned:")
                for row in results:
                    name = row.get('name', 'N/A')
                    gc = row.get('gold_cost')
                    r1 = row.get('roll_match1')
                    r2 = row.get('roll_match2')
                    sh = row.get('shadow_count', 0) or 0
                    ho = row.get('holy_count', 0) or 0
                    so = row.get('soldier_count', 0) or 0
                    wo = row.get('worker_count', 0) or 0
                    exp = row.get('expansion')
                    
                    roles = []
                    if sh: roles.append(f"{sh} Shadow")
                    if ho: roles.append(f"{ho} Holy")
                    if so: roles.append(f"{so} Soldier")
                    if wo: roles.append(f"{wo} Worker")
                    role_str = ", ".join(roles) if roles else "No roles"
                    roll_str = f"{r1}" + (f"/{r2}" if r2 and r2 > 0 else "")
                    gc_str = f"{gc}gp" if gc is not None else "N/A"
                    exp_str = f" | {exp}" if exp else ""
                    print(f"         {name:20} | Cost: {gc_str:5} | Roll: {roll_str:5} | {role_str:20}{exp_str}")
            
            elif card_type == 'Monsters':
                print(f"      {card_type} returned:")
                for row in results:
                    name = row.get('name', 'N/A')
                    area = row.get('area')
                    mtype = row.get('monster_type')
                    sc = row.get('strength_cost', 0) or 0
                    mc = row.get('magic_cost', 0) or 0
                    vp = row.get('vp_reward', 0) or 0
                    gr = row.get('gold_reward', 0) or 0
                    exp = row.get('expansion')
                    
                    cost_str = f"{sc}sp" + (f" + {mc}mp" if mc else "")
                    reward_str = f"{vp}vp" + (f" + {gr}gp" if gr else "")
                    exp_str = f" | {exp}" if exp else ""
                    print(f"         {name:25} | {area:10} | {mtype:8} | Cost: {cost_str:10} | Reward: {reward_str:15}{exp_str}")
            
            elif card_type == 'Domains':
                print(f"      {card_type} returned:")
                for row in results:
                    name = row.get('name', 'N/A')
                    gc = row.get('gold_cost')
                    vp = row.get('vp_reward')
                    text = row.get('text')
                    
                    text_preview = (text[:50] + "...") if text and len(text) > 50 else (text or "No effect")
                    print(f"         {name:25} | Cost: {gc:2}gp | {vp}vp | {text_preview}")
            
            elif card_type == 'Dukes':
                print(f"      {card_type} returned:")
                for row in results:
                    name = row.get('name', 'N/A')
                    gm = row.get('gold_mult', 0) or 0
                    sm = row.get('strength_mult', 0) or 0
                    mm = row.get('magic_mult', 0) or 0
                    
                    mults = []
                    if gm: mults.append(f"Gold×{gm}")
                    if sm: mults.append(f"Str×{sm}")
                    if mm: mults.append(f"Mag×{mm}")
                    mult_str = ", ".join(mults) if mults else "No multipliers"
                    print(f"         {name:30} | {mult_str}")
            
        except mariadb.Error as e:
            print(f"      ✗ Error calling {proc_name}: {e}")
    
    # Cleanup
    cursor.close()
    connection.close()
    print("\n" + "=" * 50)
    print("Database test completed")
    return True


if __name__ == "__main__":
    success = test_database_connection()
    sys.exit(0 if success else 1)

