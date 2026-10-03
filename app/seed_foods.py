"""Seed data for the foods catalogue: common Indian foods with approximate per-serving values.

Every number is a rough estimate for a typical home-style serving; real values vary with recipe and portion.
Order matters: earlier rows are shown first when the user searches with an empty query ("popular").
`seed_foods` is idempotent (insert-if-missing by name) and is called at app startup and in test fixtures.
"""

import logging

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Food

log = logging.getLogger("seed")

# (name, aliases comma separated, serving, kcal, protein_g, carbs_g, fat_g, fibre_g)
FOODS: list[tuple[str, str, str, float, float, float, float, float]] = [
    # --- popular staples ---
    ("Roti (phulka)", "chapati,phulka,fulka,wheat roti", "1 medium (40 g)", 105, 3.2, 20, 1.2, 2.8),
    ("Plain rice, cooked", "chawal,steamed rice,white rice", "1 cup (150 g)", 195, 4, 43, 0.4, 0.6),
    ("Dal tadka", "toor dal,arhar dal,yellow dal,dal fry", "1 katori (150 g)", 160, 8, 20, 5, 4.5),
    ("Egg, boiled", "anda,boiled egg,ubla anda", "1 large (50 g)", 78, 6.3, 0.6, 5.3, 0),
    ("Paneer bhurji", "paneer scramble", "1 katori (120 g)", 270, 14, 6, 21, 1.2),
    ("Curd (dahi)", "dahi,yogurt,yoghurt,plain curd", "1 katori (100 g)", 62, 3.5, 4.7, 3.3, 0),
    ("Banana", "kela", "1 medium (100 g)", 90, 1.1, 23, 0.3, 2.6),
    ("Apple", "seb", "1 medium (150 g)", 78, 0.4, 21, 0.3, 3.6),
    ("Masala chai", "chai,tea with milk,milk tea", "1 cup (150 ml)", 70, 2, 10, 2.5, 0),
    ("Idli", "idly,steamed rice cake", "2 pieces (100 g)", 130, 4, 27, 0.4, 1.2),
    ("Plain dosa", "dosai,sada dosa", "1 medium (80 g)", 135, 3, 24, 3, 1),
    ("Masala dosa", "potato dosa", "1 medium (180 g)", 250, 5.5, 37, 9, 2.5),
    ("Sambar", "sambhar,lentil vegetable stew", "1 katori (150 g)", 90, 4.5, 13, 2.5, 3.5),
    ("Poha", "flattened rice,kanda poha,aval upma", "1 plate (150 g)", 250, 5, 42, 7, 2.5),
    ("Upma", "rava upma,suji upma,semolina upma", "1 plate (180 g)", 265, 6, 38, 9, 2.5),
    ("Aloo paratha", "potato paratha,paratha with aloo", "1 medium (100 g)", 270, 6, 38, 10, 3),
    ("Rajma", "kidney bean curry,rajma masala", "1 katori (150 g)", 190, 9, 27, 5, 7),
    ("Chole", "chana masala,chickpea curry,chhole", "1 katori (150 g)", 210, 9, 28, 7, 8),
    ("Chicken curry", "murgh curry,chicken masala", "1 katori (150 g)", 230, 22, 6, 13, 1.2),
    ("Palak paneer", "spinach paneer,saag paneer", "1 katori (150 g)", 240, 12, 8, 17, 3),
    # --- breads and rice dishes ---
    ("Plain paratha", "paratha,tawa paratha", "1 medium (70 g)", 200, 4.5, 28, 8, 2.5),
    ("Roti with ghee", "ghee roti,chapati with ghee", "1 medium (45 g)", 140, 3.2, 20, 5.5, 2.8),
    ("Bajra roti", "pearl millet roti,bajre ki roti", "1 medium (50 g)", 135, 4, 25, 2.5, 3.5),
    ("Jowar roti", "sorghum roti,jolada rotti", "1 medium (50 g)", 130, 3.5, 27, 1, 3),
    ("Ragi roti", "finger millet roti,nachni roti", "1 medium (50 g)", 125, 3, 25, 1, 3.5),
    ("Makki di roti", "maize roti,corn roti", "1 medium (60 g)", 150, 3.5, 30, 2, 3.5),
    ("Naan", "tandoori naan,butter naan", "1 piece (90 g)", 260, 8, 45, 5, 2),
    ("Puri", "poori,fried bread", "2 pieces (60 g)", 240, 4, 28, 12, 2),
    ("Bhatura", "bhature,chole bhature bread", "1 piece (80 g)", 280, 6, 36, 12, 1.5),
    ("Thepla", "methi thepla,gujarati thepla", "1 piece (40 g)", 110, 3, 15, 4, 2),
    ("Brown rice, cooked", "brown chawal", "1 cup (150 g)", 165, 3.7, 35, 1.3, 2.7),
    ("Jeera rice", "cumin rice", "1 cup (150 g)", 235, 4, 42, 5, 0.8),
    ("Vegetable pulao", "veg pulao,pulav,pulao", "1 cup (180 g)", 250, 5, 42, 7, 3),
    ("Veg biryani", "vegetable biryani,biriyani veg", "1 plate (250 g)", 380, 8, 58, 12, 4),
    ("Chicken biryani", "murgh biryani,biriyani chicken", "1 plate (300 g)", 490, 25, 58, 17, 2.5),
    ("Egg biryani", "anda biryani", "1 plate (280 g)", 440, 16, 58, 15, 2.5),
    ("Khichdi", "moong dal khichdi,dal khichdi,khichri", "1 bowl (250 g)", 270, 10, 44, 6, 4.5),
    ("Curd rice", "dahi chawal,thayir sadam,mosaru anna", "1 bowl (200 g)", 230, 6, 36, 6, 0.8),
    ("Lemon rice", "chitranna,nimbu chawal", "1 cup (180 g)", 260, 5, 43, 7, 1.5),
    ("Tamarind rice", "puliyogare,pulihora", "1 cup (180 g)", 280, 5, 45, 9, 2),
    ("Rajma chawal", "rajma with rice", "1 plate (300 g)", 400, 14, 70, 6, 8),
    # --- dals and legumes ---
    ("Moong dal", "yellow moong,moong dal curry", "1 katori (150 g)", 140, 8.5, 20, 3, 4),
    ("Masoor dal", "red lentil dal,red lentils", "1 katori (150 g)", 150, 9, 22, 3, 5),
    ("Chana dal", "bengal gram dal", "1 katori (150 g)", 180, 10, 26, 4, 6),
    ("Urad dal", "black gram dal,maa ki dal", "1 katori (150 g)", 190, 10, 25, 5.5, 6),
    ("Dal makhani", "makhani dal,black dal", "1 katori (150 g)", 230, 9, 22, 12, 6),
    ("Sprouts salad", "moong sprouts,sprouted moong,sprouts chaat", "1 bowl (100 g)", 95, 7, 13, 0.6, 3.5),
    ("Boiled chana", "boiled chickpeas,kala chana,chana", "1 katori (100 g)", 165, 9, 27, 2.7, 7.6),
    ("Lobia curry", "black eyed peas curry,chawli", "1 katori (150 g)", 175, 9, 25, 4, 6),
    ("Soya chunks curry", "soya chunk,meal maker curry,nutrela", "1 katori (150 g)", 200, 18, 14, 8, 5),
    ("Hummus", "chickpea dip", "2 tbsp (30 g)", 70, 2.5, 5, 4.5, 1.5),
    # --- vegetable dishes ---
    ("Aloo gobi", "potato cauliflower,aloo gobhi", "1 katori (150 g)", 150, 3.5, 18, 7, 3.5),
    ("Bhindi masala", "okra fry,bhindi fry,lady finger", "1 katori (120 g)", 130, 3, 11, 8.5, 4),
    ("Baingan bharta", "brinjal bharta,eggplant bharta", "1 katori (150 g)", 140, 3, 12, 9, 5),
    ("Mixed veg curry", "mixed vegetable sabzi,sabji", "1 katori (150 g)", 125, 3.5, 14, 6, 4),
    ("Lauki sabzi", "bottle gourd curry,dudhi,ghia", "1 katori (150 g)", 85, 2, 10, 4, 2.5),
    ("Palak sabzi", "spinach sabzi,saag", "1 katori (150 g)", 110, 4.5, 8, 7, 4),
    ("Matar paneer", "peas paneer,mutter paneer", "1 katori (150 g)", 260, 12, 12, 18, 3.5),
    ("Paneer butter masala", "paneer makhani,butter paneer", "1 katori (150 g)", 320, 12, 12, 26, 2),
    ("Kadai paneer", "kadhai paneer", "1 katori (150 g)", 290, 13, 10, 22, 2.5),
    ("Aloo jeera", "jeera aloo,potato fry", "1 katori (120 g)", 160, 2.5, 22, 7, 2.5),
    ("Aloo matar", "potato peas curry", "1 katori (150 g)", 170, 4.5, 23, 7, 4),
    ("Cabbage sabzi", "patta gobhi,cabbage poriyal", "1 katori (120 g)", 100, 2.5, 9, 6, 3),
    ("Beans poriyal", "french beans fry,green beans sabzi", "1 katori (120 g)", 105, 3, 10, 6, 4),
    ("Methi sabzi", "fenugreek sabzi,methi aloo", "1 katori (120 g)", 115, 3.5, 10, 7, 4),
    ("Kadhi", "punjabi kadhi,gujarati kadhi,kadhi pakora", "1 katori (150 g)", 130, 5, 11, 7, 1),
    ("Sarson da saag", "mustard greens curry,sarson saag", "1 katori (150 g)", 150, 5.5, 10, 10, 5),
    ("Mushroom masala", "mushroom curry,khumb masala", "1 katori (150 g)", 150, 5, 9, 10, 2.5),
    ("Tofu bhurji", "tofu scramble", "1 katori (120 g)", 170, 14, 5, 11, 1.5),
    # --- non-veg ---
    ("Egg curry", "anda curry,egg masala", "2 eggs with gravy (200 g)", 290, 15, 8, 22, 1.5),
    ("Omelette", "masala omelette,egg omelet,omelet", "2 eggs (110 g)", 190, 13, 2, 14, 0.5),
    ("Egg bhurji", "anda bhurji,egg scramble", "2 eggs (120 g)", 215, 13, 4, 16, 0.8),
    ("Butter chicken", "murgh makhani", "1 katori (150 g)", 320, 21, 9, 22, 1),
    ("Tandoori chicken", "chicken tikka,tandoori murgh", "2 pieces (150 g)", 260, 30, 4, 14, 0.5),
    ("Grilled chicken breast", "chicken breast,boiled chicken", "100 g", 165, 31, 0, 3.6, 0),
    ("Fish curry", "machli curry,meen curry,fish masala", "1 katori (150 g)", 210, 20, 6, 12, 1),
    ("Fish fry", "tawa fish,fried fish", "1 piece (100 g)", 220, 20, 6, 13, 0.5),
    ("Mutton curry", "gosht curry,lamb curry,mutton masala", "1 katori (150 g)", 340, 24, 6, 25, 1),
    ("Keema", "mutton keema,minced meat curry", "1 katori (150 g)", 320, 22, 6, 23, 1.5),
    ("Prawn curry", "shrimp curry,jhinga curry", "1 katori (150 g)", 190, 20, 6, 10, 1),
    ("Chicken biryani raita", "raita with biryani", "1 katori (100 g)", 70, 3.5, 5, 4, 0.5),
    # --- breakfast and snacks ---
    ("Besan chilla", "besan cheela,gram flour pancake", "1 medium (80 g)", 150, 7, 15, 7, 3),
    ("Moong dal chilla", "moong chilla,moong cheela", "1 medium (80 g)", 130, 8, 15, 4, 3.5),
    ("Oats porridge", "oatmeal,oats,daliya oats", "1 bowl (200 g)", 160, 6, 27, 3.5, 4),
    ("Vegetable daliya", "broken wheat porridge,dalia", "1 bowl (200 g)", 210, 7, 37, 4, 6),
    ("Sweet daliya", "dalia with milk", "1 bowl (200 g)", 230, 8, 40, 4.5, 5),
    ("Medu vada", "vada,urad vada,medhu vadai", "1 piece (50 g)", 135, 4, 14, 7, 2),
    ("Uttapam", "uthappam,onion uttapam", "1 medium (120 g)", 190, 5, 30, 5.5, 2),
    ("Pesarattu", "green gram dosa,moong dosa", "1 medium (90 g)", 140, 7, 20, 3.5, 3.5),
    ("Appam", "palappam", "1 piece (60 g)", 100, 1.8, 20, 1.5, 0.5),
    ("Pongal", "ven pongal,khara pongal", "1 bowl (200 g)", 280, 8, 40, 10, 2),
    ("Sabudana khichdi", "sago khichdi,sabudana", "1 plate (150 g)", 330, 4, 52, 12, 1.5),
    ("Bread toast with butter", "toast,butter toast", "2 slices (60 g)", 190, 5, 28, 6.5, 2),
    ("Brown bread sandwich", "veg sandwich,vegetable sandwich", "1 sandwich (130 g)", 230, 8, 33, 7, 4),
    ("Peanut butter toast", "pb toast", "2 slices (80 g)", 330, 12, 30, 18, 5),
    ("Samosa", "aloo samosa", "1 piece (80 g)", 260, 4, 28, 15, 2.5),
    ("Pakora", "bhajiya,bhajji,onion pakoda,pakoda", "5 pieces (80 g)", 230, 5, 20, 14, 3),
    ("Vada pav", "wada pav,batata vada pav", "1 piece (130 g)", 290, 6, 40, 12, 3),
    ("Pav bhaji", "bhaji pav", "1 plate with 2 pav (300 g)", 500, 12, 68, 20, 8),
    ("Dhokla", "khaman dhokla,khaman", "3 pieces (100 g)", 160, 6, 24, 4.5, 2),
    ("Khandvi", "gujarati khandvi", "5 rolls (80 g)", 130, 5, 14, 6, 1.5),
    ("Bhel puri", "bhelpuri,bhel", "1 plate (100 g)", 190, 4, 32, 5, 3),
    ("Pani puri", "golgappa,puchka,gol gappe", "6 pieces (120 g)", 180, 3, 32, 5, 2.5),
    ("Chana chaat", "chickpea chaat,kala chana chaat", "1 bowl (120 g)", 190, 9, 28, 4.5, 7),
    ("Roasted makhana", "fox nuts,phool makhana,lotus seeds", "1 cup (30 g)", 105, 3.5, 22, 0.3, 1.5),
    ("Roasted chana", "bhuna chana,roasted chickpeas", "30 g", 110, 6, 18, 2, 5),
    ("Murmura (puffed rice)", "puffed rice,mamra,kurmura", "1 cup (20 g)", 80, 1.5, 18, 0.2, 0.5),
    ("Khakhra", "gujarati khakhra,methi khakhra", "2 pieces (30 g)", 120, 3.5, 20, 3, 3),
    ("Namkeen mixture", "bhujia,chivda,mixture", "30 g", 170, 4, 14, 11, 2),
    ("Biscuits (Marie)", "marie biscuit,tea biscuits", "4 pieces (28 g)", 120, 2, 21, 3, 0.5),
    ("Rusk", "toast rusk,tea rusk", "2 pieces (20 g)", 80, 2, 15, 1.5, 0.5),
    # --- dairy and drinks ---
    ("Milk, full fat", "doodh,whole milk,full cream milk", "1 glass (200 ml)", 130, 6.4, 9.6, 7, 0),
    ("Milk, toned", "toned milk,doodh", "1 glass (200 ml)", 115, 6, 9.4, 6, 0),
    ("Milk, skimmed", "skim milk,double toned milk", "1 glass (200 ml)", 70, 7, 10, 0.4, 0),
    ("Lassi, sweet", "meethi lassi,sweet lassi", "1 glass (250 ml)", 200, 6, 30, 6, 0),
    ("Chaas", "buttermilk,masala chaas,mattha,moru", "1 glass (250 ml)", 40, 2, 4, 1.5, 0),
    ("Paneer, raw", "cottage cheese,paneer cubes", "100 g", 265, 18, 3.5, 20, 0),
    ("Raita", "boondi raita,cucumber raita,veg raita", "1 katori (100 g)", 75, 3.5, 6, 4, 0.5),
    ("Filter coffee", "south indian coffee,coffee with milk", "1 cup (150 ml)", 80, 3, 9, 3.5, 0),
    ("Black coffee", "coffee,americano", "1 cup (200 ml)", 5, 0.3, 0.8, 0, 0),
    ("Green tea", "tea without milk,black tea", "1 cup (200 ml)", 3, 0, 0.5, 0, 0),
    ("Coconut water", "nariyal pani,tender coconut water", "1 glass (250 ml)", 50, 0.5, 12, 0.3, 1.5),
    ("Fresh lime water", "nimbu pani,lemonade,shikanji", "1 glass (250 ml)", 60, 0.2, 15, 0, 0.2),
    ("Protein shake (whey)", "whey protein,protein powder shake", "1 scoop in water (30 g)", 120, 24, 3, 1.5, 0),
    ("Sugarcane juice", "ganne ka ras", "1 glass (250 ml)", 180, 0.5, 45, 0, 0),
    ("Orange juice", "fresh orange juice,mosambi juice", "1 glass (250 ml)", 110, 1.5, 26, 0.5, 0.5),
    ("Cold drink (cola)", "soft drink,coke,pepsi,soda", "1 can (330 ml)", 140, 0, 35, 0, 0),
    ("Badam milk", "almond milk,kesar badam milk", "1 glass (200 ml)", 190, 7, 22, 8, 1),
    # --- fruit ---
    ("Mango", "aam,alphonso,mango slices", "1 cup (165 g)", 100, 1.4, 25, 0.6, 2.6),
    ("Papaya", "papita", "1 cup (150 g)", 65, 0.7, 16, 0.4, 2.5),
    ("Orange", "santra,narangi", "1 medium (130 g)", 60, 1.2, 15, 0.2, 3.1),
    ("Guava", "amrud,peru", "1 medium (100 g)", 68, 2.6, 14, 1, 5.4),
    ("Watermelon", "tarbooz", "1 cup (150 g)", 45, 0.9, 11, 0.2, 0.6),
    ("Grapes", "angoor", "1 cup (150 g)", 100, 1, 26, 0.3, 1.4),
    ("Pomegranate", "anar", "1/2 cup seeds (80 g)", 65, 1.3, 14, 0.9, 3.5),
    ("Pineapple", "ananas", "1 cup (150 g)", 75, 0.8, 20, 0.2, 2.2),
    ("Chikoo", "sapota,sapodilla", "1 medium (100 g)", 83, 0.4, 20, 1.1, 5.3),
    ("Dates (khajur)", "dates,khajoor", "3 pieces (24 g)", 70, 0.5, 18, 0.1, 2),
    ("Mixed nuts", "dry fruits,almonds cashews,nuts", "1 handful (25 g)", 150, 5, 6, 12.5, 2.5),
    ("Almonds", "badam", "10 pieces (12 g)", 70, 2.5, 2.6, 6, 1.5),
    ("Peanuts, roasted", "moongphali,groundnuts,mungfali", "1 handful (30 g)", 170, 7.5, 5, 14, 2.5),
    ("Walnuts", "akhrot", "5 halves (15 g)", 100, 2.3, 2, 10, 1),
    ("Chia seed pudding", "chia pudding", "1 bowl (150 g)", 190, 6, 18, 10, 9),
    # --- sweets and treats ---
    ("Gulab jamun", "gulabjamun", "1 piece (40 g)", 150, 2, 22, 6, 0.2),
    ("Jalebi", "jilebi", "2 pieces (50 g)", 200, 1.5, 36, 6, 0.2),
    ("Rasgulla", "rosogolla,rasagulla", "1 piece (50 g)", 105, 2.5, 22, 1, 0),
    ("Kheer", "rice kheer,payasam,phirni", "1 katori (120 g)", 190, 5, 30, 6, 0.3),
    ("Besan laddu", "laddoo,ladoo", "1 piece (40 g)", 190, 3.5, 22, 10, 1.5),
    ("Halwa (suji)", "sooji halwa,sheera,rava kesari", "1 katori (100 g)", 270, 3.5, 38, 12, 1),
    ("Gajar halwa", "carrot halwa,gajrela", "1 katori (100 g)", 230, 4, 28, 12, 2),
    ("Ice cream", "vanilla ice cream,kulfi", "1 scoop (70 g)", 140, 2.4, 16, 7, 0.4),
    ("Dark chocolate", "chocolate,choco", "2 squares (20 g)", 110, 1.5, 9, 8, 2),
    ("Sugar", "cheeni,shakkar", "1 tsp (5 g)", 20, 0, 5, 0, 0),
    # --- fats, sauces, extras ---
    ("Ghee", "clarified butter,desi ghee", "1 tsp (5 g)", 45, 0, 0, 5, 0),
    ("Butter", "makhan", "1 tsp (5 g)", 36, 0, 0, 4, 0),
    ("Cooking oil", "sunflower oil,mustard oil,refined oil,tel", "1 tsp (5 ml)", 45, 0, 0, 5, 0),
    ("Green chutney", "mint chutney,pudina chutney,coriander chutney", "2 tbsp (30 g)", 20, 0.8, 3, 0.5, 1),
    ("Coconut chutney", "nariyal chutney", "2 tbsp (30 g)", 55, 0.8, 2, 5, 1.2),
    ("Tomato soup", "tamatar soup", "1 bowl (200 ml)", 80, 2, 14, 2, 1.5),
    ("Vegetable soup", "veg soup,mixed veg soup", "1 bowl (200 ml)", 65, 2.5, 11, 1.5, 2.5),
    ("Green salad", "kachumber,cucumber tomato onion salad,salad", "1 bowl (100 g)", 30, 1.2, 6, 0.2, 2),
    ("Peanut chikki", "groundnut chikki,chikki,gajak", "1 piece (30 g)", 150, 3.5, 17, 8, 1.5),
    ("Pizza slice", "veg pizza,cheese pizza", "1 slice (110 g)", 280, 11, 33, 11, 2),
    ("French fries", "chips,aloo fries", "1 medium (100 g)", 310, 3.5, 40, 15, 3.5),
    ("Veg burger", "aloo tikki burger,burger", "1 burger (170 g)", 340, 9, 45, 14, 3.5),
    ("Maggi noodles", "instant noodles,maggi,masala noodles", "1 packet (70 g)", 320, 7, 44, 13, 2),
    ("Hakka noodles", "veg noodles,chowmein,chow mein", "1 plate (250 g)", 420, 10, 62, 15, 4),
    ("Veg momos", "momo,steamed momos,dumplings", "6 pieces (150 g)", 240, 8, 40, 5, 3),
]


async def seed_foods(maker: async_sessionmaker[AsyncSession]) -> int:
    """Inserts any catalogue foods that are missing (by name). Safe to call on every startup. Returns rows added."""
    rows = [
        {
            "name": n, "aliases": a.lower(), "serving": s, "kcal": k, "protein_g": p, "carbs_g": c,
            "fat_g": f, "fibre_g": fi, "popularity": i,
        }
        for i, (n, a, s, k, p, c, f, fi) in enumerate(FOODS)
    ]
    async with maker() as session:
        stmt = pg_insert(Food).values(rows).on_conflict_do_nothing(index_elements=["name"])
        result = await session.execute(stmt.returning(Food.id))
        added = len(result.all())
        await session.commit()
    if added:
        log.info("seeded %d foods", added)
    return added
