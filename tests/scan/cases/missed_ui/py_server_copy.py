import logging

from fastapi import HTTPException

log = logging.getLogger(__name__)


def init(app):
    app.config.setdefault('TABLE_VIEW_TITLE', 'View')
    app.config.setdefault('TABLE_ACTIONS_TITLE', 'Actions')
    app.config.setdefault('TABLE_PK_PLACEHOLDER', ':id')
    app.config.setdefault('BOOTSTRAP_SERVE_LOCAL', True)


def get_result(game_id):
    log.info("Looking up the game result for the dashboard")
    if game_id is None:
        raise HTTPException(status_code=404, detail="Game result not found")
    if game_id < 0:
        raise ValueError("game id must be positive when calling lookup")
    return {"error": "Could not load the quiz right now"}
