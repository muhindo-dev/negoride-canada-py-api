"""Preloaded popular places (spec §21.3 item 7): major Canadian airports, train /
bus stations and malls. Static data — the app caches it and shows it before any
network autocomplete call. Coordinates are public landmark locations."""

# (id, kind, name, short, province, lat, lng, address)
_RAW = [
    # ── airports ──
    ('YYZ', 'airport', 'Toronto Pearson International Airport', 'YYZ', 'ON', 43.6777, -79.6248, '6301 Silver Dart Dr, Mississauga, ON L5P 1B2'),
    ('YTZ', 'airport', 'Billy Bishop Toronto City Airport', 'YTZ', 'ON', 43.6275, -79.3962, '1 Island Airport, Toronto, ON M5V 1A1'),
    ('YOW', 'airport', 'Ottawa Macdonald–Cartier International Airport', 'YOW', 'ON', 45.3225, -75.6692, '1000 Airport Pkwy Private, Ottawa, ON K1V 9B4'),
    ('YHM', 'airport', 'John C. Munro Hamilton International Airport', 'YHM', 'ON', 43.1736, -79.9350, '9300 Airport Rd, Mount Hope, ON L0R 1W0'),
    ('YKF', 'airport', 'Region of Waterloo International Airport', 'YKF', 'ON', 43.4608, -80.3786, '4881 Fountain St N, Breslau, ON N0B 1M0'),
    ('YXU', 'airport', 'London International Airport', 'YXU', 'ON', 43.0356, -81.1539, '1750 Crumlin Sideroad, London, ON N5V 3B6'),
    ('YQG', 'airport', 'Windsor International Airport', 'YQG', 'ON', 42.2756, -82.9556, '3200 County Rd 42, Windsor, ON N8V 0A1'),
    ('YVR', 'airport', 'Vancouver International Airport', 'YVR', 'BC', 49.1967, -123.1815, '3211 Grant McConachie Way, Richmond, BC V7B 0A4'),
    ('YYJ', 'airport', 'Victoria International Airport', 'YYJ', 'BC', 48.6469, -123.4258, '1640 Electra Blvd, North Saanich, BC V8L 5V4'),
    ('YLW', 'airport', 'Kelowna International Airport', 'YLW', 'BC', 49.9561, -119.3778, '5533 Airport Way, Kelowna, BC V1V 1S1'),
    ('YXX', 'airport', 'Abbotsford International Airport', 'YXX', 'BC', 49.0253, -122.3608, '30440 Liberator Ave, Abbotsford, BC V2T 6H5'),
    ('YUL', 'airport', 'Montréal–Trudeau International Airport', 'YUL', 'QC', 45.4706, -73.7408, '975 Roméo-Vachon Blvd N, Dorval, QC H4Y 1H1'),
    ('YQB', 'airport', 'Québec City Jean Lesage International Airport', 'YQB', 'QC', 46.7911, -71.3933, '505 Rue Principale, Québec, QC G2G 0J4'),
    ('YYC', 'airport', 'Calgary International Airport', 'YYC', 'AB', 51.1215, -114.0076, '2000 Airport Rd NE, Calgary, AB T2E 6W5'),
    ('YEG', 'airport', 'Edmonton International Airport', 'YEG', 'AB', 53.3097, -113.5800, '1000 Airport Rd, Edmonton, AB T9E 0V3'),
    ('YWG', 'airport', 'Winnipeg Richardson International Airport', 'YWG', 'MB', 49.9100, -97.2399, '2000 Wellington Ave, Winnipeg, MB R3H 1C2'),
    ('YXE', 'airport', 'Saskatoon John G. Diefenbaker International Airport', 'YXE', 'SK', 52.1708, -106.6997, '2625 Airport Dr, Saskatoon, SK S7L 7L1'),
    ('YQR', 'airport', 'Regina International Airport', 'YQR', 'SK', 50.4319, -104.6658, '5201 Regina Ave, Regina, SK S4W 1B3'),
    ('YHZ', 'airport', 'Halifax Stanfield International Airport', 'YHZ', 'NS', 44.8808, -63.5086, '1 Bell Blvd, Goffs, NS B2T 1K2'),
    ('YQM', 'airport', 'Greater Moncton Roméo LeBlanc International Airport', 'YQM', 'NB', 46.1122, -64.6786, '777 Aviation Ave, Dieppe, NB E1A 7Z5'),
    ('YFC', 'airport', 'Fredericton International Airport', 'YFC', 'NB', 45.8689, -66.5372, '2570 Route 102, Lincoln, NB E3B 9G1'),
    ('YSJ', 'airport', 'Saint John Airport', 'YSJ', 'NB', 45.3161, -65.8903, '4180 Loch Lomond Rd, Saint John, NB E2N 1L7'),
    ('YYG', 'airport', 'Charlottetown Airport', 'YYG', 'PE', 46.2900, -63.1211, '250 Maple Hills Ave, Charlottetown, PE C1C 1N2'),
    ('YYT', 'airport', "St. John's International Airport", 'YYT', 'NL', 47.6186, -52.7519, "100 World Pkwy, St. John's, NL A1A 5T2"),
    ('YXY', 'airport', 'Erik Nielsen Whitehorse International Airport', 'YXY', 'YT', 60.7096, -135.0674, '75 Barkley Grow Crescent, Whitehorse, YT'),
    ('YZF', 'airport', 'Yellowknife Airport', 'YZF', 'NT', 62.4628, -114.4403, '1 Yellowknife Airport, Yellowknife, NT X1A 3T2'),
    # ── train / bus stations ──
    ('union-station-toronto', 'station', 'Union Station', 'Union', 'ON', 43.6453, -79.3806, '65 Front St W, Toronto, ON M5J 1E6'),
    ('union-station-bus-terminal', 'station', 'Union Station Bus Terminal', 'Union Bus', 'ON', 43.6425, -79.3787, '81 Bay St, Toronto, ON M5J 0E7'),
    ('ottawa-station', 'station', 'Ottawa Train Station', 'Ottawa VIA', 'ON', 45.4166, -75.6517, '200 Tremblay Rd, Ottawa, ON K1G 3H5'),
    ('gare-centrale', 'station', 'Gare Centrale de Montréal', 'Gare Centrale', 'QC', 45.4999, -73.5664, '895 Rue De la Gauchetière O, Montréal, QC H3B 4G1'),
    ('gare-du-palais', 'station', 'Gare du Palais', 'Gare du Palais', 'QC', 46.8175, -71.2139, '450 Rue de la Gare-du-Palais, Québec, QC G1K 3X2'),
    ('pacific-central', 'station', 'Pacific Central Station', 'Pacific Central', 'BC', 49.2733, -123.0975, '1150 Station St, Vancouver, BC V6A 4C7'),
    ('waterfront-station', 'station', 'Waterfront Station', 'Waterfront', 'BC', 49.2856, -123.1115, '601 W Cordova St, Vancouver, BC V6B 1G1'),
    ('edmonton-station', 'station', 'Edmonton Station (VIA Rail)', 'Edmonton VIA', 'AB', 53.5794, -113.5458, '12360 121 St NW, Edmonton, AB T5L 5C3'),
    ('winnipeg-union-station', 'station', 'Winnipeg Union Station', 'Winnipeg Union', 'MB', 49.8889, -97.1344, '123 Main St, Winnipeg, MB R3C 1A3'),
    ('halifax-station', 'station', 'Halifax Station', 'Halifax VIA', 'NS', 44.6394, -63.5669, '1161 Hollis St, Halifax, NS B3H 2P6'),
    # ── malls ──
    ('eaton-centre', 'mall', 'CF Toronto Eaton Centre', 'Eaton Centre', 'ON', 43.6544, -79.3807, '220 Yonge St, Toronto, ON M5B 2H1'),
    ('yorkdale', 'mall', 'Yorkdale Shopping Centre', 'Yorkdale', 'ON', 43.7255, -79.4522, '3401 Dufferin St, Toronto, ON M6A 2T9'),
    ('square-one', 'mall', 'Square One Shopping Centre', 'Square One', 'ON', 43.5931, -79.6425, '100 City Centre Dr, Mississauga, ON L5B 2C9'),
    ('rideau-centre', 'mall', 'CF Rideau Centre', 'Rideau Centre', 'ON', 45.4254, -75.6922, '50 Rideau St, Ottawa, ON K1N 9J7'),
    ('carrefour-laval', 'mall', 'CF Carrefour Laval', 'Carrefour Laval', 'QC', 45.5700, -73.7514, '3003 Boul le Carrefour, Laval, QC H7T 1C7'),
    ('centre-eaton-montreal', 'mall', 'Centre Eaton de Montréal', 'Centre Eaton', 'QC', 45.5033, -73.5711, '705 Rue Sainte-Catherine O, Montréal, QC H3B 4G5'),
    ('metropolis', 'mall', 'Metropolis at Metrotown', 'Metrotown', 'BC', 49.2266, -123.0003, '4700 Kingsway, Burnaby, BC V5H 4M1'),
    ('pacific-centre', 'mall', 'CF Pacific Centre', 'Pacific Centre', 'BC', 49.2826, -123.1178, '701 W Georgia St, Vancouver, BC V7Y 1G5'),
    ('chinook-centre', 'mall', 'CF Chinook Centre', 'Chinook', 'AB', 50.9981, -114.0731, '6455 Macleod Trail SW, Calgary, AB T2H 0K8'),
    ('west-edmonton-mall', 'mall', 'West Edmonton Mall', 'WEM', 'AB', 53.5225, -113.6242, '8882 170 St NW, Edmonton, AB T5T 4J2'),
    ('polo-park', 'mall', 'CF Polo Park', 'Polo Park', 'MB', 49.8817, -97.1981, '1485 Portage Ave, Winnipeg, MB R3G 0W4'),
    ('halifax-shopping-centre', 'mall', 'Halifax Shopping Centre', 'HSC', 'NS', 44.6497, -63.6197, '7001 Mumford Rd, Halifax, NS B3L 2H8'),
]

PLACES = [
    {'id': r[0], 'kind': r[1], 'name': r[2], 'short_name': r[3], 'province': r[4],
     'lat': r[5], 'lng': r[6], 'address': r[7]}
    for r in _RAW
]
PROVINCES = ('AB', 'BC', 'MB', 'NB', 'NL', 'NS', 'NT', 'NU', 'ON', 'PE', 'QC', 'SK', 'YT')


def popular(province=None, kind=None):
    out = PLACES
    if province:
        p = province.strip().upper()
        out = [x for x in out if x['province'] == p]
    if kind:
        out = [x for x in out if x['kind'] == kind]
    order = {'airport': 0, 'station': 1, 'mall': 2}
    return sorted(out, key=lambda x: (order.get(x['kind'], 9), x['province'], x['name']))
