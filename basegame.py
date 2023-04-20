import mysql.connector
import json
import random

class Card:
    def __init__(self):
        self.name = ""
        self.isVisible = False
        self.isAccessible = False
class Game:
    def __init__(self):
        self.board 
class Player:
    def __init__(self):
        self.name = "Player"
        self.ownedStarters = []
        self.ownedCitizens = []
        self.ownedDomains = []
        self.ownedDukes = []
        self.ownedMonsters = []
        self.goldScore = 2
        self.strengthScore = 0
        self.magicScore = 1
        self.isFirst = False
        self.shadowCount = 0
        self.holyCount = 0
        self.soldierCount = 0
        self.workerCount = 0
    def display(self):
        print(self.name)
        print(f"Gold: {self.goldScore} Strength: {self.strengthScore} Magic: {self.magicScore}")
        print(f"Starters: {len(self.ownedStarters)} Citizens: {len(self.ownedCitizens)} Monsters: {len(self.ownedMonsters)} Domains: {len(self.ownedDomains)}")
        if self.shadowCount != 0:
            tempChar = ''
            if self.shadowCount > 1:
                tempChar = 's'
            print(f"{self.shadowCount} Shadow icon{tempChar}")
        if self.holyCount != 0:
            tempChar = ''
            if self.holyCount > 1:
                tempChar = 's'
            print(f"{self.holyCount} Holy icon{tempChar}")
        if self.soldierCount != 0:
            tempChar = ''
            if self.soldierCount > 1:
                tempChar = 's'
            print(f"{self.soldierCount} Soldier icon{tempChar}")
        if self.workerCount != 0:
            tempChar = ''
            if self.workerCount > 1:
                tempChar = 's'
            print(f"{self.workerCount} Worker icon{tempChar}")
        print(f"Starters:")
        for starter in self.ownedStarters:
            print(f"{starter.name} {starter.rollMatch1} {starter.rollMatch2} {starter.goldPayoutOnTurn} {starter.goldPayoutOffTurn} {starter.strengthPayoutOnTurn} {starter.strengthPayoutOffTurn}")
        for citizen in self.ownedCitizens:
            print(f"{citizen.name} {citizen.goldCost} {citizen.rollMatch1} {citizen.rollMatch2} {citizen.goldPayoutOnTurn} {citizen.goldPayoutOffTurn} {citizen.strengthPayoutOnTurn} {citizen.strengthPayoutOffTurn}")
        for monster in self.ownedMonsters:
            print(f"{monster.name} {citizen.goldCost} {citizen.rollMatch1} {citizen.rollMatch2} {citizen.goldPayoutOnTurn} {citizen.goldPayoutOffTurn} {citizen.strengthPayoutOnTurn} {citizen.strengthPayoutOffTurn}")
    def calc_roles(self):
        for citizen in self.ownedCitizens:
            self.shadowCount = self.shadowCount + citizen.shadowCount
            self.holyCount = self.holyCount + citizen.holyCount
            self.soldierCount = self.soldierCount + citizen.soldierCount
            self.workerCount = self.workerCount + citizen.workerCount
        for domain in self.ownedDomains:
            self.shadowCount = self.shadowCount + domain.shadowCount
            self.holyCount = self.holyCount + domain.holyCount
            self.soldierCount = self.soldierCount + domain.soldierCount
            self.workerCount = self.workerCount + domain.workerCount

class Starter(Card):
    def __init__(self, name, roll_match1, roll_match2, gold_payout_on_turn, gold_payout_off_turn, strength_payout_on_turn, strength_payout_off_turn, magic_payout_on_turn, magic_payout_off_turn, has_special_payout_on_turn, has_special_payout_off_turn, special_payout_on_turn, special_payout_off_turn):
        self.name = name
        self.rollMatch1 = roll_match1
        self.rollMatch2 = roll_match2
        self.goldPayoutOnTurn = gold_payout_on_turn
        self.goldPayoutOffTurn = gold_payout_off_turn
        self.strengthPayoutOnTurn = strength_payout_on_turn
        self.strengthPayoutOffTurn = strength_payout_off_turn
        self.magicPayoutOnTurn = magic_payout_on_turn
        self.magicPayoutOffTurn = magic_payout_off_turn
        self.hasSpecialPayoutOnTurn = has_special_payout_on_turn
        self.hasSpecialPayoutOffTurn = has_special_payout_off_turn
        self.specialPayoutOnTurn = special_payout_on_turn
        self.specialPayoutOffTurn = special_payout_off_turn

class Citizen(Card):
    def __init__(self, name, gold_cost, roll_match1, roll_match2, shadow_count, holy_count, soldier_count, worker_count, gold_payout_on_turn, gold_payout_off_turn, strength_payout_on_turn, strength_payout_off_turn, magic_payout_on_turn, magic_payout_off_turn, has_special_payout_on_turn, has_special_payout_off_turn, special_payout_on_turn, special_payout_off_turn, special_citizen):
        self.name = name
        self.goldCost = gold_cost
        self.rollMatch1 = roll_match1
        self.rollMatch2 = roll_match2
        self.shadowCount = shadow_count
        self.holyCount = holy_count
        self.soldierCount = soldier_count
        self.workerCount = worker_count
        self.goldPayoutOnTurn = gold_payout_on_turn
        self.goldPayoutOffTurn = gold_payout_off_turn
        self.strengthPayoutOnTurn = strength_payout_on_turn
        self.strengthPayoutOffTurn = strength_payout_off_turn
        self.magicPayoutOnTurn = magic_payout_on_turn
        self.magicPayoutOffTurn = magic_payout_off_turn
        self.hasSpecialPayoutOnTurn = has_special_payout_on_turn
        self.hasSpecialPayoutOffTurn = has_special_payout_off_turn
        self.specialPayoutOnTurn = special_payout_on_turn
        self.specialPayoutOffTurn = special_payout_off_turn
        self.specialCitizen = special_citizen
    def display(self):
        print(f"\n{self.name}")
        print(f"Cost: {self.goldCost} Gold")
        if self.shadowCount != 0:
            tempChar = ''
            if self.shadowCount > 1:
                tempChar = 's'
            print(f"{self.shadowCount} Shadow icon{tempChar}")
        if self.holyCount != 0:
            tempChar = ''
            if self.holyCount > 1:
                tempChar = 's'
            print(f"{self.holyCount} Holy icon{tempChar}")
        if self.soldierCount != 0:
            tempChar = ''
            if self.soldierCount > 1:
                tempChar = 's'
            print(f"{self.soldierCount} Soldier icon{tempChar}")
        if self.workerCount != 0:
            tempChar = ''
            if self.workerCount > 1:
                tempChar = 's'
            print(f"{self.workerCount} Worker icon{tempChar}")

class Domain(Card):
    def __init__(self, input_name, gold_cost, shadow_count, holy_count, soldier_count, worker_count, vp_reward, has_activation_effect, has_passive_effect, passive_effect, activation_effect, input_text):
        self.name = input_name
        self.goldCost = gold_cost
        self.shadowCount = shadow_count
        self.holyCount = holy_count
        self.soldierCount = soldier_count
        self.workerCount = worker_count
        self.vpReward = vp_reward
        self.hasActivationEffect = has_activation_effect
        self.hasPassiveEffect = has_passive_effect
        self.passiveEffect = passive_effect
        self.activationEffect = activation_effect
        self.text = input_text
    def display(self):
        print("\n%s" % self.name)
        print("Cost: {} Gold".format(self.goldCost))
        if self.shadowCount != 0:
            tempChar = ''
            if self.shadowCount > 1:
                tempChar = 's'
            print(f"{self.shadowCount} Shadow icon{tempChar}")
        if self.holyCount != 0:
            tempChar = ''
            if self.holyCount > 1:
                tempChar = 's'
            print(f"{self.holyCount} Holy icon{tempChar}")
        if self.soldierCount != 0:
            tempChar = ''
            if self.soldierCount > 1:
                tempChar = 's'
            print(f"{self.soldierCount} Soldier icon{tempChar}")
        if self.workerCount != 0:
            tempChar = ''
            if self.workerCount > 1:
                tempChar = 's'
            print(f"{self.workerCount} Worker icon{tempChar}")
        print(self.text)

class Monster(Card):
    def __init__(self, input_name, input_area, input_type, input_order, strength_cost, magic_cost, vp_reward, gold_reward, strength_reward, magic_reward, has_special_reward, special_reward, has_special_cost, special_cost, is_extra):
        self.name = input_name
        self.area = input_area
        self.type = input_type
        self.order = input_order
        self.strengthCost = strength_cost
        self.magicCost = magic_cost
        self.vpReward = vp_reward
        self.goldReward = gold_reward
        self.strengthReward = strength_reward
        self.magicReward = magic_reward
        self.hasSpecialReward = has_special_reward
        self.specialReward = special_reward
        self.hasSpecialCost = has_special_cost
        self.specialCost = special_cost
        self.isExtra = is_extra
    def display(self):
        print(f"{self.name} is a {self.type} from {self.area}")
    def add_strength_cost(self, addedStrength):
        self.strengthCost = self.strengthCost + addedStrength
    def add_magic_cost(self, addedMagic):
        self.magicCost = self.magicCost + addedMagic

class Duke(Card):
    def __init__(self, input_name, gold_mult, strength_mult, magic_mult, shadow_mult, holy_mult, soldier_mult, worker_mult, monster_mult, citizen_mult, domain_mult, boss_mult, minion_mult, beast_mult, titan_mult):
        self.name = input_name
        self.goldMultiplier = gold_mult
        self.strengthMultiplier = strength_mult
        self.magicMultiplier = magic_mult
        self.shadowMultiplier = shadow_mult
        self.holyMultiplier = holy_mult
        self.soldierMultiplier = soldier_mult
        self.workerMultiplier = worker_mult
        self.monsterMultiplier = monster_mult
        self.citizenMultiplier = citizen_mult
        self.domainMultiplier = domain_mult
        self.bossMultiplier = boss_mult
        self.minionMultiplier = minion_mult
        self.beastMultiplier = beast_mult
        self.titanMultiplier = titan_mult
        
    def display(self):
        print("\n%s" % self.name)
        if (self.goldMultiplier != self.strengthMultiplier):
            resourceScore = 1/float(self.strengthMultiplier)
            print(f"1 Victory Point per gold and {resourceScore:.2f} per Strength/Magic")
        else:
            resourceScore = 1/float(self.goldMultiplier)
            print(f"{resourceScore:.2f} Victory Points per resource")
        if self.shadowMultiplier != 0:
            tempChar = ''
            if self.shadowMultiplier > 1:
                tempChar = 's'
            print(f"{self.shadowMultiplier} Victory Point{tempChar} per Shadow")
        if self.holyMultiplier != 0:
            tempChar = ''
            if self.holyMultiplier > 1:
                tempChar = 's'
            print(f"{self.holyMultiplier} Victory Point{tempChar} per Holy")
        if self.soldierMultiplier != 0:
            tempChar = ''
            if self.soldierMultiplier > 1:
                tempChar = 's'
            print(f"{self.soldierMultiplier} Victory Point{tempChar} per Soldier")
        if self.workerMultiplier != 0:
            tempChar = ''
            if self.workerMultiplier > 1:
                tempChar = 's'
            print(f"{self.workerMultiplier} Victory Point{tempChar} per Worker")
        if self.monsterMultiplier != 0:
            tempChar = ''
            if self.monsterMultiplier > 1:
                tempChar = 's'
            print(f"{self.monsterMultiplier} Victory Point{tempChar} per Monster")
        if self.citizenMultiplier != 0:
            tempChar = ''
            if self.citizenMultiplier > 1:
                tempChar = 's'
            print(f"{self.citizenMultiplier} Victory Point{tempChar} per Citizen")
        if self.domainMultiplier != 0:
            tempChar = ''
            if self.domainMultiplier > 1:
                tempChar = 's'
            print(f"{self.domainMultiplier} Victory Point{tempChar} per Domain")
        if self.bossMultiplier != 0:
            tempChar = ''
            if self.bossMultiplier > 1:
                tempChar = 's'
            print(f"{self.bossMultiplier} Victory Point{tempChar} per Boss")
        if self.titanMultiplier != 0:
            tempChar = ''
            if self.titanMultiplier > 1:
                tempChar = 's'
            print(f"{self.titanMultiplier} Victory Point{tempChar} per Titan")
   

class Board:
    def __init__(self, player_count, input_preset):
        self.playerCount = player_count
        self.preset = input_preset
        self.playerList = []
        self.citizenGrid = []
        self.domainGrid = []
        self.monsterGrid = []
        self.dukeStack = []
        self.domainStack = []
        self.citizenStack = []
        self.monsterStack = []
        self.starterStack = []
        self.dieOne = 0
        self.dieTwo = 0
        self.dieSum = 0
        self.exhaustedCount = 0
        
        myConnect = mysql.connector.connect(user='vckonline', password='vckonline', host='localhost', database='vckonline')
        myCursor = myConnect.cursor(dictionary = True)
#load game data
        myCursor.execute("SELECT * FROM dukes")
        myResult = myCursor.fetchall()
        for row in myResult:
            myDuke = Duke(row['name'], row['gold_mult'], row['strength_mult'], row['magic_mult'], row['shadow_mult'], row['holy_mult'], row['soldier_mult'], row['worker_mult'], row['monster_mult'], row['citizen_mult'], row['domain_mult'], row['boss_mult'], row['minion_mult'], row['beast_mult'], row['titan_mult'])
            self.dukeStack.append(myDuke)
        random.shuffle(self.dukeStack)
        #for duke in self.dukeStack:
        #    duke.display()
        myCursor.execute("SELECT * FROM domains")
        myResult = myCursor.fetchall()
        for row in myResult:
            myDomain = Domain(row['name'], row['gold_cost'], row['shadow_count'], row['holy_count'], row['soldier_count'], row['worker_count'], row['vp_reward'], row['has_activation_effect'], row['has_passive_effect'], row['passive_effect'], row['activation_effect'], row['text'])
            self.domainStack.append(myDomain)
        random.shuffle(self.domainStack)
        #for domain in self.domainStack:
        #    domain.display()

        myCursor.execute("SELECT * FROM citizens")
        myResult = myCursor.fetchall()
        for row in myResult:
            myCitizen = Citizen(row['name'], row['gold_cost'], row['roll_match1'], row['roll_match2'], row['shadow_count'], row['holy_count'], row['soldier_count'], row['worker_count'], row['gold_payout_on_turn'], row['gold_payout_off_turn'], row['strength_payout_on_turn'], row['strength_payout_off_turn'], row['magic_payout_on_turn'], row['magic_payout_off_turn'], row['has_special_payout_on_turn'], row['has_special_payout_off_turn'], row['special_payout_on_turn'], row['special_payout_off_turn'], row['special_citizen'])
            self.citizenStack.append(myCitizen)
        random.shuffle(self.citizenStack)
        #for citizen in self.citizenStack:
        #    citizen.display()
        
        myCursor.execute("SELECT * FROM starters")
        myResult = myCursor.fetchall()
        for row in myResult:
            myStarter = Starter(row['name'], row['roll_match1'], row['roll_match2'], row['gold_payout_on_turn'], row['gold_payout_off_turn'], row['strength_payout_on_turn'], row['strength_payout_off_turn'], row['magic_payout_on_turn'], row['magic_payout_off_turn'], row['has_special_payout_on_turn'], row['has_special_payout_off_turn'], row['special_payout_on_turn'], row['special_payout_off_turn'])
            self.starterStack.append(myStarter)
        
        myCursor.execute("SELECT * FROM monsters")
        myResult = myCursor.fetchall()
        for row in myResult:
            myMonster = Monster(row['name'], row['area'], row['type'], row['order'], row['strength_cost'], row['magic_cost'], row['vp_reward'], row['gold_reward'], row['strength_reward'], row['magic_reward'], row['has_special_reward'], row['special_reward'], row['has_special_cost'], row['special_cost'], row['is_extra'])
            self.monsterStack.append(myMonster)
        #for monster in self.monsterStack:
        #    monster.display()
        myConnect.close()
#end load game data and set up board
#create player list and establish order
        for x in range(0, self.playerCount):
            myPlayer = Player()
            myPlayer.name = "Player %s" % (x + 1)
            self.playerList.append(myPlayer)
        random.shuffle(self.playerList)
        self.playerList[0].isFirst = True
        for player in self.playerList:
            player.ownedStarters.append(self.starterStack[0])
            player.ownedStarters.append(self.starterStack[1])

    def roll_phase(self):
        self.dieOne = random.randint(1, 6)
        self.dieTwo = random.randint(1, 6)
        self.dieSum = self.dieOne + self.dieTwo
        print(f"{self.dieOne} | {self.dieTwo} | {self.dieSum}")
        for citizen in self.playerList[0].ownedCitizens:
            if (citizen.rollMatch1 == self.dieOne) or (citizen.rollMatch1 == self.dieTwo) or (citizen.rollMatch1 == self.dieSum) or (citizen.rollMatch2 == self.dieSum):
                print(f"{citizen.name} Payout")
                self.playerList[0].goldScore = self.playerList[0].goldScore + citizen.goldPayoutOnTurn
                self.playerList[0].strengthScore = self.playerList[0].strengthScore + citizen.strengthPayoutOnTurn
                self.playerList[0].magicScore = self.playerList[0].magicScore + citizen.magicPayoutOnTurn
        listIterator = iter(self.playerList)
        next(listIterator)
        for player in listIterator:
            for citizen in player.ownedCitizens:
                if (citizen.rollMatch1 == self.dieOne) or (citizen.rollMatch1 == self.dieTwo) or (citizen.rollMatch1 == self.dieSum) or (citizen.rollMatch2 == self.dieSum):
                    print(f"{citizen.name} Payout")
                    player.goldScore = player.goldScore + citizen.goldPayoutOffTurn
                    player.strengthScore = player.strengthScore + citizen.strengthPayoutOffTurn
                    player.magicScore = player.magicScore + citizen.magicPayoutOffTurn
                    
    def play_turn(self):
        self.display()
        print("new turn")
        print("roll phase")
        self.roll_phase()
        
    def display(self):
        for player in self.playerList:
            player.display()
            
    def end_check(self):
        if self.exhaustedCount <= (self.playerCount*2):
            return False

