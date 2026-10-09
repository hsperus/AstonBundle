"""Fictional residence used by `python manage.py seed`. Images: living/seed_images/<slug>.webp (AI-generated)."""

BUILDING = {
    "name": "Bundle House",
    "image": "building",
    "image_alt": "Five-storey red-brick student residence with a glass entrance and a large purple AstonBundle sign",
}

# slug, name, price/week, weeks, m², bed, bathroom, kitchen, available, accessible, sort, summary, alt, features, description
ROOMS = [
    ("classic-ensuite", "Classic En-suite", "189.00", 44, 13, "Three-quarter bed (120 cm)", "Private shower room", "Shared kitchen (6 students)",
     14, False, 1, "Our most popular room: your own shower room and a shared kitchen for six.",
     "En-suite student bedroom with a three-quarter bed, oak desk and a purple cushion with the AstonBundle logo",
     "Private en-suite shower room\nDesk, chair, lamp and pinboard\nWardrobe and under-bed storage\nAll bills and Wi-Fi included",
     "A bright, practical room with everything you need for first year. You share a modern kitchen and dining area with five flatmates, "
     "so it is easy to make friends from day one."),
    ("premium-ensuite", "Premium En-suite", "209.00", 44, 16, "Double bed (135 cm)", "Larger private shower room", "Shared kitchen (5 students)",
     8, False, 2, "More space, a double bed and a bigger desk, with a smaller shared kitchen.",
     "Larger en-suite bedroom with a double bed, wide oak desk, armchair and a purple AstonBundle cushion",
     "Double bed\nWide desk with monitor stand\nArmchair\nAll bills and Wi-Fi included",
     "For students who want a little more room to study and relax. The flat has five bedrooms sharing one kitchen."),
    ("studio", "Studio", "259.00", 51, 21, "Double bed (135 cm)", "Private shower room", "Private kitchenette",
     5, False, 3, "Your own self-contained space with a private kitchenette.",
     "Student studio with a double bed, kitchenette, dining table for two and a sofa with an AstonBundle cushion",
     "Private kitchenette with hob, sink and fridge\nDining table for two\nSofa\nAll bills and Wi-Fi included",
     "Ideal for postgraduates and anyone who prefers their own kitchen. You still have full access to every shared space in the building."),
    ("accessible-studio", "Accessible Studio", "259.00", 51, 28, "Double bed (135 cm)", "Level-access wet room with grab rails", "Private kitchenette with lowered counter",
     2, True, 4, "A spacious, wheelchair-accessible studio with a level-access wet room.",
     "Wheelchair-accessible studio with an open floor, height-adjustable desk, lowered kitchenette and a wet room",
     "Step-free from street to room\nHeight-adjustable desk\nLowered kitchenette counter\nVisual fire alarm and emergency pull cord\nAll bills and Wi-Fi included",
     "Designed with disabled students. Tell us about your needs in your booking request and we will adapt the room before you arrive."),
]

# slug, name, icon, sort, summary, alt
FACILITIES = [
    ("reception", "24/7 reception and parcel lockers", "home", 1,
     "Staffed day and night. Your AstonBundle order waits for you in the parcel lockers.",
     "Reception lobby with an oak desk, parcel lockers and a purple wall with the AstonBundle logo"),
    ("kitchen", "Shared kitchens", "pot", 2,
     "Modern kitchens with two hobs, ovens and a big dining table for every flat.",
     "Shared student kitchen with a long dining table and a purple AstonBundle wall panel"),
    ("study", "Study lounge", "book", 3,
     "Quiet desks, bookable group booths and fast Wi-Fi, open 24 hours.",
     "Study lounge with oak desks, group booths and the AstonBundle logo etched on glass"),
    ("cinema", "Cinema room", "spark", 4,
     "Tiered seats and a big screen for film nights. Book it free for your flat.",
     "Small cinema room with purple seats and the AstonBundle logo on the screen"),
    ("games", "Games room", "users", 5,
     "Pool, table football, consoles and sofas. Weekly events run by the residence team.",
     "Games room with a pool table, table football, sofas and a purple AstonBundle neon sign"),
    ("gym", "Residents' gym", "zap", 6,
     "Cardio machines and free weights, included in your rent.",
     "Residents' gym with treadmills, bikes, dumbbells and the AstonBundle logo on a purple wall"),
    ("terrace", "Rooftop terrace", "sun", 7,
     "Outdoor seating with a view over the Birmingham skyline.",
     "Rooftop terrace at sunset with seating, festoon lights and a purple AstonBundle parasol"),
]

INCLUDED = ["All bills included: energy, water, Wi-Fi", "Contents insurance", "24/7 reception and CCTV",
            "Cleaning of shared areas", "Bike storage", "Six-minute walk to campus"]
