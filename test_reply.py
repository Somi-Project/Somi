from handlers.twitter import TwitterHandler

def test_reply():
    handler = TwitterHandler()
    try:
        # Use the synchronous wrapper to get mentions
        mentions = handler.get_mentions_sync()
        for mention in mentions:
            print(f"Mention: @{mention['username']} - {mention['text']} (ID: {mention['id']})")
            reply = f"@{mention['username']} Hey hon, coffee’s up—what’s your vibe?"
            result = handler.post_sync(reply, mention['username'])
            print(f"Replied: {reply}")
            print(result)
    except Exception as e:
        print(f"Error: {str(e)}")
        # Save page source for debugging if mentions fail
        page_content = "No page content available"
        if handler.page:
            try:
                page_content = handler.page.content()
            except Exception as page_error:
                print(f"Error retrieving page content: {page_error}")
        with open("page_source.html", "w", encoding="utf-8") as f:
            f.write(page_content)

if __name__ == "__main__":
    test_reply()