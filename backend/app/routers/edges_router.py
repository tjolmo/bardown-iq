from fastapi import APIRouter, Depends, HTTPException

from app.database import AsyncSessionLocal
from app.dependencies import get_db
from app.edge_board import get_board
from app.schemas.player import EdgeBoardOut

router = APIRouter(prefix="/edges", tags=["edges"])


@router.get("/players", status_code=200, response_model=EdgeBoardOut)
async def get_players_with_edge(db = Depends(get_db)):
    """Players on the next slate with at least one prop the model prices at a positive expected return, best edge
    first, each with all of his priced props. Cached per game day and rebuilt in the background (app/edge_board.py)."""
    try:
        return await get_board(db, AsyncSessionLocal)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error building the edge board: {e}")
