from app.models.reaction import MessageReaction


def test_message_reaction_tablename() -> None:
    assert MessageReaction.__tablename__ == "message_reactions"
