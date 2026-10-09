import { apiGet } from "./client";
import type { EdgeBoard } from "../types/edges";

export const getEdgeBoard = () => apiGet<EdgeBoard>("/edges/players");
