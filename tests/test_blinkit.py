from services.scrapers.blinkit import scrape_blinkit

def test():
    result = scrape_blinkit("Kellogs Chocos")
    print(result)

if __name__ == "__main__":
    test()