import sys
import os
import time
import random
import datetime

import pygame
import chess
import chess.pgn

try:
    import chess.engine  # noqa: F401  (kept available for future Stockfish support)
    HAS_ENGINE_MODULE = True
except ImportError:
    HAS_ENGINE_MODULE = False

try:
    import pyperclip
    HAS_CLIPBOARD = True
except ImportError:
    HAS_CLIPBOARD = False

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


# ══════════════════════════════════════════════════════════════════════════
# THEMES
# ══════════════════════════════════════════════════════════════════════════

THEMES = {
    "wood": {
        "light":      (240, 217, 181),
        "dark":       (181, 136, 99),
        "background": (54, 42, 30),
        "panel":      (74, 58, 42),
        "panel_btn":  (96, 76, 55),
        "text":       (240, 230, 210),
        "highlight":  (246, 216, 105),
        "last_move":  (205, 180, 90),
        "legal_dot":  (30, 30, 30),
        "check":      (220, 60, 60),
        "border":     (30, 22, 15),
    },
    "tournament_green": {
        "light":      (238, 238, 210),
        "dark":       (118, 150, 86),
        "background": (35, 35, 35),
        "panel":      (48, 48, 48),
        "panel_btn":  (66, 66, 66),
        "text":       (230, 230, 230),
        "highlight":  (246, 246, 130),
        "last_move":  (186, 202, 68),
        "legal_dot":  (20, 20, 20),
        "check":      (220, 60, 60),
        "border":     (20, 20, 20),
    },
    "dark_mode": {
        "light":      (100, 104, 112),
        "dark":       (46, 49, 55),
        "background": (18, 18, 22),
        "panel":      (26, 26, 32),
        "panel_btn":  (40, 40, 48),
        "text":       (220, 220, 230),
        "highlight":  (90, 170, 230),
        "last_move":  (60, 110, 170),
        "legal_dot":  (90, 200, 255),
        "check":      (230, 70, 70),
        "border":     (8, 8, 10),
    },
}
THEME_ORDER = ["wood", "tournament_green", "dark_mode"]

UNICODE_PIECES = {
    'P': '\u2659', 'N': '\u2658', 'B': '\u2657', 'R': '\u2656', 'Q': '\u2655', 'K': '\u2654',
    'p': '\u265F', 'n': '\u265E', 'b': '\u265D', 'r': '\u265C', 'q': '\u265B', 'k': '\u265A',
}

# ── Piece visual styles ───────────────────────────────────────────────────
# Three genuinely different rendering approaches, all self-contained
# (no external image assets needed, so they work on any machine):
#
#   classic_unicode    — traditional Unicode chess glyphs (♔♕♖...)
#   minimalist_vector  — flat geometric icons drawn with pygame primitives
#   letter_notation    — bold letter (K/Q/R/B/N/P) inside a coloured disc
PIECE_STYLES = ["classic_unicode", "minimalist_vector", "letter_notation"]
PIECE_STYLE_LABELS = {
    "classic_unicode":   "Classic",
    "minimalist_vector": "Minimalist",
    "letter_notation":   "Letters",
}


# ══════════════════════════════════════════════════════════════════════════
# CHESS CLOCK  (Fischer increment + Bronstein delay)
# ══════════════════════════════════════════════════════════════════════════

class ChessClock:
    """
    FISCHER   — after a player completes a move, `increment` seconds are
                ADDED to their remaining time.

    BRONSTEIN — before a move, the player has up to `increment` seconds of
                "free" thinking time that is NOT deducted from their clock.
                Move within that window and the clock is unchanged; move
                slower and only the time beyond the increment is deducted.
    """

    def __init__(self, initial_minutes=10, increment_seconds=5, mode="fischer"):
        self.initial_seconds = initial_minutes * 60
        self.increment = increment_seconds
        self.mode = mode              # "fischer" | "bronstein" | None (disabled)
        self.enabled = mode is not None

        self.remaining = {chess.WHITE: float(self.initial_seconds),
                           chess.BLACK: float(self.initial_seconds)}
        self.active_color = chess.WHITE
        self.running = False
        self._move_start_time = None

    def reset(self, initial_minutes=None, increment_seconds=None, mode="__unset__"):
        if initial_minutes is not None:
            self.initial_seconds = initial_minutes * 60
        if increment_seconds is not None:
            self.increment = increment_seconds
        if mode != "__unset__":
            self.mode = mode
            self.enabled = mode is not None
        self.remaining = {chess.WHITE: float(self.initial_seconds),
                           chess.BLACK: float(self.initial_seconds)}
        self.active_color = chess.WHITE
        self.running = False
        self._move_start_time = None

    def start_turn(self, color):
        if not self.enabled:
            return
        self.active_color = color
        self._move_start_time = time.time()
        self.running = True

    def get_display_time(self, color):
        if not self.enabled:
            return None
        if color == self.active_color and self.running and self._move_start_time:
            elapsed = time.time() - self._move_start_time
            return max(0.0, self.remaining[color] - elapsed)
        return self.remaining[color]

    def complete_move(self):
        """Call right after the active player's move is pushed to the board."""
        if not self.enabled or self._move_start_time is None:
            return
        elapsed = time.time() - self._move_start_time
        color = self.active_color

        if self.mode == "fischer":
            self.remaining[color] = max(0.0, self.remaining[color] - elapsed) + self.increment
        elif self.mode == "bronstein":
            deduction = max(0.0, elapsed - self.increment)
            self.remaining[color] = max(0.0, self.remaining[color] - deduction)

        self.running = False
        self._move_start_time = None

    def is_flagged(self, color):
        if not self.enabled:
            return False
        t = self.get_display_time(color)
        return t is not None and t <= 0.0

    @staticmethod
    def format_time(seconds):
        if seconds is None:
            return "--:--"
        seconds = max(0, int(seconds))
        m, s = divmod(seconds, 60)
        return f"{m:02d}:{s:02d}"


CLOCK_PRESETS = [
    ("Fischer 10+5",   10, 5, "fischer"),
    ("Fischer 5+3",     5, 3, "fischer"),
    ("Bronstein 10+5", 10, 5, "bronstein"),
    ("Bronstein 5+3",   5, 3, "bronstein"),
    ("No Clock",        0, 0, None),
]


# ══════════════════════════════════════════════════════════════════════════
# GAME ENGINE — wraps python-chess with undo/redo, PGN, FEN, sandbox editing
# ══════════════════════════════════════════════════════════════════════════

class GameEngine:
    def __init__(self):
        self.board = chess.Board()
        self.redo_stack = []          # moves popped by undo, available for redo
        self.san_history = []         # SAN notation for each played move
        self.game_start_time = datetime.datetime.now()
        self.event_name = "A.R.I.S.E. Casual Game"
        self.white_name = "Player"
        self.black_name = "A.R.I.S.E. AI"

    # ── Moves ─────────────────────────────────────────────────────────────
    def push_move(self, move: chess.Move) -> bool:
        if move not in self.board.legal_moves:
            return False
        san = self.board.san(move)
        self.board.push(move)
        self.san_history.append(san)
        self.redo_stack.clear()       # a new move invalidates redo history
        return True

    def undo(self) -> bool:
        if not self.board.move_stack:
            return False
        move = self.board.pop()
        self.redo_stack.append(move)
        if self.san_history:
            self.san_history.pop()
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        move = self.redo_stack.pop()
        san = self.board.san(move)
        self.board.push(move)
        self.san_history.append(san)
        return True

    def legal_destinations(self, from_square: int) -> list:
        return [m.to_square for m in self.board.legal_moves if m.from_square == from_square]

    def last_move(self):
        return self.board.move_stack[-1] if self.board.move_stack else None

    def new_game(self):
        self.board = chess.Board()
        self.redo_stack.clear()
        self.san_history.clear()
        self.game_start_time = datetime.datetime.now()

    # ── FEN ───────────────────────────────────────────────────────────────
    def export_fen(self) -> str:
        return self.board.fen()

    def import_fen(self, fen_string: str) -> bool:
        try:
            new_board = chess.Board(fen_string.strip())
            self.board = new_board
            self.redo_stack.clear()
            self.san_history.clear()   # importing a position discards prior move history
            return True
        except Exception:
            return False

    # ── PGN ───────────────────────────────────────────────────────────────
    def export_pgn(self) -> str:
        game = chess.pgn.Game()
        game.headers["Event"]  = self.event_name
        game.headers["Date"]   = self.game_start_time.strftime("%Y.%m.%d")
        game.headers["White"]  = self.white_name
        game.headers["Black"]  = self.black_name
        game.headers["Result"] = self.board.result()

        node = game
        for move in self.board.move_stack:
            node = node.add_variation(move)

        return str(game)

    def save_pgn(self, filepath: str) -> bool:
        try:
            with open(filepath, "w") as f:
                f.write(self.export_pgn())
            return True
        except Exception:
            return False

    # ── Sandbox / Board Editor ───────────────────────────────────────────
    def clear_board_for_editing(self):
        self.board = chess.Board(None)   # completely empty board, no pieces
        self.board.turn = chess.WHITE
        self.redo_stack.clear()
        self.san_history.clear()

    def set_piece(self, square: int, piece):
        self.board.set_piece_at(square, piece)

    def remove_piece(self, square: int):
        self.board.remove_piece_at(square)

    def finalize_sandbox(self, turn=chess.WHITE) -> bool:
        """Validates the manually-built position and returns True if playable."""
        self.board.turn = turn
        try:
            self.board.clean_castling_rights()
        except Exception:
            pass
        white_kings = len(self.board.pieces(chess.KING, chess.WHITE))
        black_kings = len(self.board.pieces(chess.KING, chess.BLACK))
        return white_kings == 1 and black_kings == 1


# ══════════════════════════════════════════════════════════════════════════
# AI OPPONENT
# ══════════════════════════════════════════════════════════════════════════

PIECE_VALUES = {
    chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
    chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 0,
}


# ══════════════════════════════════════════════════════════════════════════
# EVALUATION HELPERS — used by the "hard", "greedy" and "reserved" styles
# ══════════════════════════════════════════════════════════════════════════

def _piece_square_bonus(piece_type, square, color) -> float:
    """
    Lightweight positional heuristic (no hardcoded tables to mis-copy —
    computed directly from file/rank so it's easy to reason about and test).
    Rewards central knights/bishops, advancing/central pawns, rooks on the
    7th rank, and a king that stays tucked on the back rank.
    """
    rank = chess.square_rank(square)          # 0..7, 0 = rank 1
    file = chess.square_file(square)          # 0..7, 0 = file a
    if color == chess.BLACK:
        rank = 7 - rank                       # mirror so "advancing" means the same thing for both colours

    centre_file_bonus = 4 - abs(file - 3.5)   # peaks at the d/e files

    if piece_type == chess.PAWN:
        return rank * 4 + centre_file_bonus * 2
    elif piece_type == chess.KNIGHT:
        edge_penalty = abs(file - 3.5) + abs(rank - 3.5)
        return (7 - edge_penalty) * 6
    elif piece_type == chess.BISHOP:
        edge_penalty = abs(file - 3.5) + abs(rank - 3.5)
        return (7 - edge_penalty) * 4
    elif piece_type == chess.ROOK:
        return 15 if rank == 6 else 0         # bonus for the 7th rank
    elif piece_type == chess.QUEEN:
        return centre_file_bonus * 2
    elif piece_type == chess.KING:
        return (7 - rank) * 3                 # rewards staying on the back rank
    return 0


def _attacked_value(board: chess.Board, attacker_color: bool) -> int:
    """Total value of the OPPONENT's pieces currently attacked by attacker_color."""
    defender_color = not attacker_color
    total = 0
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece and piece.color == defender_color and board.is_attacked_by(attacker_color, sq):
            total += PIECE_VALUES[piece.piece_type]
    return total


def _hanging_value(board: chess.Board, side_color: bool) -> int:
    """Value of side_color's own pieces that are attacked more times than they're defended."""
    opponent = not side_color
    total = 0
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece and piece.color == side_color and piece.piece_type != chess.KING:
            attackers = len(board.attackers(opponent, sq))
            if attackers > 0 and attackers > len(board.attackers(side_color, sq)):
                total += PIECE_VALUES[piece.piece_type]
    return total


def _king_safety(board: chess.Board, color: bool) -> int:
    """Counts the squares around color's king that the opponent does NOT attack (0-8, higher = safer)."""
    king_sq = board.king(color)
    if king_sq is None:
        return 0
    opponent = not color
    kf, kr = chess.square_file(king_sq), chess.square_rank(king_sq)
    safe = 0
    for df in (-1, 0, 1):
        for dr in (-1, 0, 1):
            if df == 0 and dr == 0:
                continue
            f, r = kf + df, kr + dr
            if 0 <= f <= 7 and 0 <= r <= 7:
                if not board.is_attacked_by(opponent, chess.square(f, r)):
                    safe += 1
    return safe


def evaluate_board(board: chess.Board, style: str = "normal") -> float:
    """
    Positive = good for White, negative = good for Black.
    `style` layers extra scoring on top of the shared material+mobility base:

      easy      — base score only; weakness comes from shallow search + noise
      normal    — base score only (material + mobility), 2-ply search
      hard      — base score + positional piece-square bonuses, 3-ply search
      greedy    — base score + a heavy bonus for attacking the opponent's
                  pieces and delivering check — relentlessly aggressive
      reserved  — base score + a heavy bonus for keeping your own pieces
                  defended and your king safe — relentlessly defensive
    """
    if board.is_checkmate():
        return -99999 if board.turn == chess.WHITE else 99999
    if board.is_stalemate() or board.is_insufficient_material():
        return 0

    score = 0
    for piece_type, value in PIECE_VALUES.items():
        score += value * len(board.pieces(piece_type, chess.WHITE))
        score -= value * len(board.pieces(piece_type, chess.BLACK))

    mobility = len(list(board.legal_moves))
    score += (2 * mobility) if board.turn == chess.WHITE else (-2 * mobility)

    if style == "hard":
        for sq in chess.SQUARES:
            piece = board.piece_at(sq)
            if piece:
                bonus = _piece_square_bonus(piece.piece_type, sq, piece.color)
                score += bonus if piece.color == chess.WHITE else -bonus

    elif style == "greedy":
        # Relentlessly attacking: heavily reward pressure on enemy pieces and checks
        attack_term = _attacked_value(board, chess.WHITE) - _attacked_value(board, chess.BLACK)
        score += 3 * attack_term
        if board.is_check():
            score += -400 if board.turn == chess.WHITE else 400

    elif style == "reserved":
        # Relentlessly defensive: heavily reward not hanging pieces and king safety
        defense_term = _hanging_value(board, chess.BLACK) - _hanging_value(board, chess.WHITE)
        score += 3 * defense_term
        safety_term = _king_safety(board, chess.WHITE) - _king_safety(board, chess.BLACK)
        score += 6 * safety_term

    # "easy" and "normal" fall through with just the base material+mobility score
    return score


def _negamax(board: chess.Board, depth: int, alpha: float, beta: float, style: str = "normal") -> float:
    if depth == 0 or board.is_game_over():
        val = evaluate_board(board, style)
        return val if board.turn == chess.WHITE else -val

    best = -float('inf')
    for move in board.legal_moves:
        board.push(move)
        score = -_negamax(board, depth - 1, -beta, -alpha, style)
        board.pop()
        if score > best:
            best = score
        alpha = max(alpha, score)
        if alpha >= beta:
            break
    return best


class ChessAI:
    """
    Five difficulty modes, each with genuinely different behaviour
    (not just a label) — see evaluate_board() docstring for what each
    style rewards, and DIFFICULTY_CONFIG below for search depth / weakness.
    """
    DIFFICULTIES = ["easy", "normal", "hard", "greedy", "reserved"]

    # depth        = how many plies ahead the engine searches
    # noise        = random jitter added to each move's score (weakens play)
    # randomize_top= pick uniformly among the top N scored moves instead of
    #                always the single best (adds human-like inconsistency)
    DIFFICULTY_CONFIG = {
        "easy":     {"depth": 1, "noise": 80,  "randomize_top": 3},
        "normal":   {"depth": 2, "noise": 0,   "randomize_top": 1},
        "hard":     {"depth": 3, "noise": 0,   "randomize_top": 1},
        "greedy":   {"depth": 2, "noise": 0,   "randomize_top": 1},
        "reserved": {"depth": 2, "noise": 0,   "randomize_top": 1},
    }

    def __init__(self, difficulty="normal"):
        self.difficulty = difficulty

    def choose_move(self, board: chess.Board):
        legal = list(board.legal_moves)
        if not legal:
            return None

        cfg = self.DIFFICULTY_CONFIG[self.difficulty]
        depth = cfg["depth"]

        random.shuffle(legal)   # ties aren't always resolved the same way
        scored = []
        for move in legal:
            board.push(move)
            val = -_negamax(board, depth - 1, -float('inf'), float('inf'), self.difficulty)
            board.pop()
            if cfg["noise"]:
                val += random.uniform(-cfg["noise"], cfg["noise"])
            scored.append((val, move))

        scored.sort(key=lambda x: x[0], reverse=True)
        top_n = scored[:cfg["randomize_top"]]
        return random.choice(top_n)[1]


# ══════════════════════════════════════════════════════════════════════════
# CHAOS MODE — "what if the board itself is an enemy?"
# ══════════════════════════════════════════════════════════════════════════

class ChaosHazards:
    """
    Every TRIGGER_INTERVAL plies (default 5), one random environmental
    event fires on the board:

      EARTHQUAKE  — an entire file shifts up or down by one square.
                    Pieces pushed off the edge are destroyed. Instantaneous —
                    the board is altered once, then normal play resumes.

      BLACK HOLE  — a gravity well opens on a random square. Anything
                    already there is destroyed immediately. It then
                    persists: on every subsequent ply, pieces within
                    BLACK_HOLE_RADIUS are pulled one step closer, and
                    anything pulled onto the centre square is destroyed.

      THAWING ICE — a few random squares become ice. If the SAME piece
                    remains on an ice square for more than two consecutive
                    plies, it falls through and is lost. The ice melts
                    away once it claims a piece.

    If a king is destroyed by any hazard, `king_lost_color` is set —
    the app treats this as an immediate, authoritative game-over and
    does not rely on python-chess's normal checkmate detection (which
    doesn't have a "your king was eaten by a black hole" concept).

    Note: hazard state (ice/black holes/log) is NOT restored by Undo —
    only the chess position and move list are. This is a deliberate
    simplification given how much extra state true environmental
    rewind would require.
    """
    TRIGGER_INTERVAL      = 5
    BLACK_HOLE_RADIUS     = 2
    MAX_BLACK_HOLES       = 3
    ICE_SQUARES_PER_EVENT = 3
    MAX_ICE_SQUARES       = 10

    def __init__(self):
        self.enabled       = False
        self.ply_counter   = 0
        self.black_holes   = []     # [{"square": int}, ...]
        self.ice_squares   = {}     # square -> {"occupant_key": str|None, "turns": int}
        self.log           = []     # human-readable event log, most recent last
        self.king_lost_color = None

    def reset(self):
        self.ply_counter = 0
        self.black_holes.clear()
        self.ice_squares.clear()
        self.log.clear()
        self.king_lost_color = None

    def _log_event(self, msg):
        self.log.append(msg)
        self.log[:] = self.log[-6:]   # keep the side panel readable

    def _occupant_key(self, board, square):
        piece = board.piece_at(square)
        return None if piece is None else piece.symbol()

    def _destroy_piece(self, board, square, reason):
        piece = board.piece_at(square)
        if piece is None:
            return
        if piece.piece_type == chess.KING:
            self.king_lost_color = piece.color
            colour_word = "White" if piece.color == chess.WHITE else "Black"
            self._log_event(f"The {colour_word} king was destroyed! ({reason})")
        else:
            self._log_event(f"{chess.piece_name(piece.piece_type).capitalize()} lost — {reason}.")
        board.remove_piece_at(square)

    # ── Called once after EVERY ply while chaos mode is enabled ───────────
    def on_move_played(self, board: chess.Board):
        if not self.enabled:
            return
        self.ply_counter += 1
        self._tick_black_holes(board)
        self._tick_ice(board)
        if self.ply_counter % self.TRIGGER_INTERVAL == 0:
            self._trigger_random_event(board)

    # ── EARTHQUAKE ──────────────────────────────────────────────────────────
    def _earthquake(self, board: chess.Board):
        file_idx  = random.randint(0, 7)
        direction = random.choice([-1, 1])

        column_pieces = {}
        for rank in range(8):
            piece = board.piece_at(chess.square(file_idx, rank))
            if piece:
                column_pieces[rank] = piece
        for rank in range(8):
            board.remove_piece_at(chess.square(file_idx, rank))

        destroyed = []
        for rank, piece in column_pieces.items():
            new_rank = rank + direction
            if 0 <= new_rank <= 7:
                board.set_piece_at(chess.square(file_idx, new_rank), piece)
            else:
                if piece.piece_type == chess.KING:
                    self.king_lost_color = piece.color
                destroyed.append(piece)

        file_letter = chess.FILE_NAMES[file_idx]
        dir_word = "up" if direction == 1 else "down"
        msg = f"EARTHQUAKE! The {file_letter}-file shifted {dir_word}."
        if destroyed:
            names = ", ".join(chess.piece_name(p.piece_type) for p in destroyed)
            msg += f" Lost off the edge: {names}."
            if any(p.piece_type == chess.KING for p in destroyed):
                colour_word = "White" if self.king_lost_color == chess.WHITE else "Black"
                msg += f" The {colour_word} king fell off the board!"
        self._log_event(msg)

    # ── BLACK HOLE ────────────────────────────────────────────────────────
    def _spawn_black_hole(self, board: chess.Board):
        empty_squares = [sq for sq in chess.SQUARES if board.piece_at(sq) is None]
        centre = random.choice(empty_squares) if empty_squares else random.choice(list(chess.SQUARES))
        if board.piece_at(centre) is not None:
            self._destroy_piece(board, centre, "swallowed by a new black hole")
        self.black_holes.append({"square": centre})
        if len(self.black_holes) > self.MAX_BLACK_HOLES:
            self.black_holes.pop(0)
        self._log_event(f"A BLACK HOLE opened at {chess.square_name(centre)}!")

    def _tick_black_holes(self, board: chess.Board):
        for hole in list(self.black_holes):
            centre = hole["square"]
            cf, cr = chess.square_file(centre), chess.square_rank(centre)

            pulls = []
            for sq in chess.SQUARES:
                if sq == centre:
                    continue
                piece = board.piece_at(sq)
                if not piece:
                    continue
                f, r = chess.square_file(sq), chess.square_rank(sq)
                dist = max(abs(f - cf), abs(r - cr))   # Chebyshev distance
                if 1 <= dist <= self.BLACK_HOLE_RADIUS:
                    step_f = f + (1 if cf > f else (-1 if cf < f else 0))
                    step_r = r + (1 if cr > r else (-1 if cr < r else 0))
                    pulls.append((sq, chess.square(step_f, step_r), piece))

            claimed = set()
            for src, dst, piece in pulls:
                if dst in claimed:
                    continue
                if board.piece_at(src) != piece:
                    continue   # already moved/consumed earlier in this tick
                board.remove_piece_at(src)
                if dst == centre:
                    if piece.piece_type == chess.KING:
                        self.king_lost_color = piece.color
                        colour_word = "White" if piece.color == chess.WHITE else "Black"
                        self._log_event(f"The {colour_word} king was pulled into the void!")
                    else:
                        self._log_event(f"{chess.piece_name(piece.piece_type).capitalize()} was pulled into the black hole.")
                else:
                    existing = board.piece_at(dst)
                    if existing is not None:
                        if existing.piece_type == chess.KING:
                            self.king_lost_color = existing.color
                        board.remove_piece_at(dst)
                    board.set_piece_at(dst, piece)
                claimed.add(dst)

    # ── THAWING ICE ───────────────────────────────────────────────────────
    def _spawn_ice(self, board: chess.Board):
        candidates = [sq for sq in chess.SQUARES if sq not in self.ice_squares]
        random.shuffle(candidates)
        chosen = candidates[:self.ICE_SQUARES_PER_EVENT]
        for sq in chosen:
            self.ice_squares[sq] = {
                "occupant_key": self._occupant_key(board, sq),
                "turns": 1 if board.piece_at(sq) else 0,
            }
        if len(self.ice_squares) > self.MAX_ICE_SQUARES:
            oldest_keys = list(self.ice_squares.keys())[: len(self.ice_squares) - self.MAX_ICE_SQUARES]
            for k in oldest_keys:
                del self.ice_squares[k]
        names = ", ".join(chess.square_name(s) for s in chosen)
        self._log_event(f"THAWING ICE has formed on {names}.")

    def _tick_ice(self, board: chess.Board):
        melted = []
        for sq, info in self.ice_squares.items():
            key = self._occupant_key(board, sq)
            if key is None:
                info["occupant_key"] = None
                info["turns"] = 0
                continue
            if key == info["occupant_key"]:
                info["turns"] += 1
            else:
                info["occupant_key"] = key
                info["turns"] = 1
            if info["turns"] > 2:
                self._destroy_piece(board, sq, "fell through the thawing ice")
                melted.append(sq)
        for sq in melted:
            del self.ice_squares[sq]   # the ice melts away after claiming a piece

    # ── DISPATCH ──────────────────────────────────────────────────────────
    def _trigger_random_event(self, board: chess.Board):
        event = random.choice(["earthquake", "black_hole", "ice"])
        if event == "earthquake":
            self._earthquake(board)
        elif event == "black_hole":
            self._spawn_black_hole(board)
        else:
            self._spawn_ice(board)


# ══════════════════════════════════════════════════════════════════════════
# VISION MODE — webcam chessboard detection (from original A.R.I.S.E.)
# ══════════════════════════════════════════════════════════════════════════

def detect_chessboard():
    """
    Opens a webcam window and looks for a physical chessboard pattern.
    Must be called from the main thread — cv2.imshow requires it on Windows.
    Blocks until 'q' is pressed, then returns control to the caller.
    """
    if not HAS_CV2:
        print("[A.R.I.S.E.] OpenCV is not installed — vision mode unavailable.")
        return

    cap = None
    for idx in range(4):
        c = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if c.isOpened():
            ret, _ = c.read()
            if ret:
                cap = c
                break
            c.release()
    if cap is None:
        for idx in range(4):
            c = cv2.VideoCapture(idx)
            if c.isOpened():
                ret, _ = c.read()
                if ret:
                    cap = c
                    break
                c.release()

    if cap is None:
        print("[A.R.I.S.E.] No working camera found.")
        return

    print("[A.R.I.S.E.] Vision mode active — press Q to close and return to the board.")
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        board_size = (7, 7)
        found, corners = cv2.findChessboardCorners(gray, board_size, None)
        if found:
            cv2.drawChessboardCorners(frame, board_size, corners, found)
            cv2.putText(frame, "Chessboard detected", (50, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.imshow('A.R.I.S.E. Vision', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    cap.release()
    cv2.destroyAllWindows()


# ══════════════════════════════════════════════════════════════════════════
# UI HELPERS
# ══════════════════════════════════════════════════════════════════════════

BOARD_PIXELS = 720
SQUARE       = BOARD_PIXELS // 8
PANEL_WIDTH  = 340
WINDOW_W     = BOARD_PIXELS + PANEL_WIDTH
WINDOW_H     = BOARD_PIXELS + 40   # small footer strip for status text


def square_to_screen(square: int, white_at_bottom: bool):
    """python-chess square (0=a1..63=h8) → top-left pixel coords."""
    file = chess.square_file(square)
    rank = chess.square_rank(square)
    if white_at_bottom:
        col = file
        row = 7 - rank
    else:
        col = 7 - file
        row = rank
    return col * SQUARE, row * SQUARE


def screen_to_square(pos, white_at_bottom: bool):
    x, y = pos
    if not (0 <= x < BOARD_PIXELS and 0 <= y < BOARD_PIXELS):
        return None
    col = x // SQUARE
    row = y // SQUARE
    if white_at_bottom:
        file = col
        rank = 7 - row
    else:
        file = 7 - col
        rank = row
    return chess.square(file, rank)


class TextInputBox:
    """Minimal single-line text box for FEN import."""
    def __init__(self, rect, font):
        self.rect = pygame.Rect(rect)
        self.font = font
        self.text = ""
        self.active = False

    def handle_key(self, event):
        if not self.active:
            return None
        if event.key == pygame.K_RETURN:
            return "submit"
        elif event.key == pygame.K_ESCAPE:
            return "cancel"
        elif event.key == pygame.K_BACKSPACE:
            self.text = self.text[:-1]
        else:
            if event.unicode and event.unicode.isprintable():
                self.text += event.unicode
        return None

    def draw(self, surface, font_color=(0, 0, 0)):
        pygame.draw.rect(surface, (255, 255, 255), self.rect)
        pygame.draw.rect(surface, (0, 0, 0), self.rect, 2)
        txt = self.font.render(self.text, True, font_color)
        surface.blit(txt, (self.rect.x + 6, self.rect.y + 6))


class Button:
    def __init__(self, rect, label, action):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.action = action

    def draw(self, surface, font, theme):
        pygame.draw.rect(surface, theme["panel_btn"], self.rect, border_radius=6)
        pygame.draw.rect(surface, theme["border"], self.rect, 2, border_radius=6)
        txt = font.render(self.label, True, theme["text"])
        tr = txt.get_rect(center=self.rect.center)
        surface.blit(txt, tr)

    def is_clicked(self, pos):
        return self.rect.collidepoint(pos)


# ══════════════════════════════════════════════════════════════════════════
# MAIN APPLICATION
# ══════════════════════════════════════════════════════════════════════════

class AriseApp:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("A.R.I.S.E. Chess")
        self.screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
        self.clock_tick = pygame.time.Clock()

        self.font        = pygame.font.SysFont("arial", 18)
        self.font_small  = pygame.font.SysFont("arial", 14)
        self.font_big    = pygame.font.SysFont("arial", 28, bold=True)

        self.engine = GameEngine()
        self.ai     = ChessAI(difficulty="normal")
        self.human_color = chess.WHITE   # human always plays White in this build

        self.theme_index = 0
        self.theme = THEMES[THEME_ORDER[self.theme_index]]

        self.clock_preset_index = 0
        preset = CLOCK_PRESETS[self.clock_preset_index]
        self.game_clock = ChessClock(preset[1], preset[2], preset[3])
        self.game_clock.start_turn(chess.WHITE)

        self.white_at_bottom = True

        # Piece visual style — cycled via the "Pieces:" panel button
        self.piece_style = "classic_unicode"
        self._piece_surface_cache = {}   # (style, symbol, size) -> pygame.Surface
        self._font_cache = {}            # (kind, size) -> pygame.font.Font

        # Selection / drag state
        self.selected_square = None
        self.legal_targets   = []
        self.dragging        = False
        self.drag_square     = None
        self.drag_pos        = (0, 0)

        # App mode: "play" or "sandbox"
        self.app_mode = "play"
        self.sandbox_selected_piece = None   # (piece_type, color) chosen from palette

        # FEN dialog state
        self.fen_dialog_active = False
        self.fen_input = TextInputBox((40, WINDOW_H // 2 - 20, BOARD_PIXELS - 80, 36), self.font)

        self.status_message = ""
        self.game_over_shown = False

        self.hazards = ChaosHazards()

        self._build_buttons()
        self._build_sandbox_palette()

    # ── Layout ────────────────────────────────────────────────────────────

    def _build_buttons(self):
        x0 = BOARD_PIXELS + 16
        w  = PANEL_WIDTH - 32
        h  = 34
        gap = 8
        y = 16
        self.buttons = []

        def add(label, action, attr_name=None):
            nonlocal y
            btn = Button((x0, y, w, h), label, action)
            self.buttons.append(btn)
            if attr_name:
                setattr(self, attr_name, btn)   # named reference for later label updates
            y += h + gap

        add("New Game",              "new_game")
        add("Undo",                  "undo")
        add("Redo",                  "redo")
        add("Toggle Sandbox Mode",   "toggle_sandbox")
        add("Import FEN",            "import_fen")
        add("Export FEN",            "export_fen")
        add("Save PGN",              "save_pgn")
        add(f"Theme: {THEME_ORDER[self.theme_index]}",
            "cycle_theme", "btn_theme")
        add(f"Clock: {CLOCK_PRESETS[self.clock_preset_index][0]}",
            "cycle_clock", "btn_clock")
        add(f"Difficulty: {self.ai.difficulty}",
            "cycle_ai", "btn_ai")
        add(f"Pieces: {PIECE_STYLE_LABELS[self.piece_style]}",
            "cycle_piece_style", "btn_piece_style")
        add("Chaos Mode: OFF",       "toggle_chaos", "btn_chaos")
        add("Flip Board",            "flip_board")
        if HAS_CV2:
            add("Vision Mode (webcam)", "vision_mode")

        self._panel_y_after_buttons = y + 10

    def _build_sandbox_palette(self):
        """12 piece swatches (6 white, 6 black) + an eraser, shown only in sandbox mode."""
        x0 = BOARD_PIXELS + 16
        size = 40
        gap = 6
        y = self._panel_y_after_buttons + 30
        self.palette_buttons = []
        order = [chess.KING, chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN]
        col = 0
        for color in (chess.WHITE, chess.BLACK):
            for pt in order:
                rect = pygame.Rect(x0 + col * (size + gap), y, size, size)
                symbol = chess.Piece(pt, color).symbol()
                self.palette_buttons.append({"rect": rect, "piece_type": pt,
                                              "color": color, "symbol": symbol})
                col += 1
                if col >= 6:
                    col = 0
                    y += size + gap
        # Eraser
        self.eraser_rect = pygame.Rect(x0, y + size + gap, size * 2, size)
        self._sandbox_panel_bottom = y + size + gap + size + 20

    # ── Game flow helpers ─────────────────────────────────────────────────

    def attempt_move(self, from_sq, to_sq):
        if self.hazards.king_lost_color is not None:
            return False   # a king has already been destroyed — game is over

        move = chess.Move(from_sq, to_sq)
        # Auto-queen promotions for simplicity
        piece = self.engine.board.piece_at(from_sq)
        if piece and piece.piece_type == chess.PAWN:
            to_rank = chess.square_rank(to_sq)
            if (piece.color == chess.WHITE and to_rank == 7) or \
               (piece.color == chess.BLACK and to_rank == 0):
                move = chess.Move(from_sq, to_sq, promotion=chess.QUEEN)

        if self.engine.push_move(move):
            self.hazards.on_move_played(self.engine.board)   # tick hazards + maybe trigger an event
            self.game_clock.complete_move()
            self.game_clock.start_turn(self.engine.board.turn)
            self.selected_square = None
            self.legal_targets = []
            self._check_game_over()
            return True
        return False

    def _check_game_over(self):
        # Hazard-induced king loss is authoritative and checked FIRST —
        # python-chess's normal checkmate/stalemate logic assumes a king
        # exists for both sides, which is no longer guaranteed in Chaos Mode.
        if self.hazards.king_lost_color is not None:
            winner = "Black" if self.hazards.king_lost_color == chess.WHITE else "White"
            loser_word = "White's" if self.hazards.king_lost_color == chess.WHITE else "Black's"
            self.status_message = f"GAME OVER — {loser_word} king was lost to the board! {winner} wins."
            return

        board = self.engine.board
        if board.is_checkmate():
            winner = "Black" if board.turn == chess.WHITE else "White"
            self.status_message = f"Checkmate — {winner} wins!"
        elif board.is_stalemate():
            self.status_message = "Draw by stalemate."
        elif board.is_insufficient_material():
            self.status_message = "Draw — insufficient material."
        elif board.can_claim_threefold_repetition():
            self.status_message = "Draw available — threefold repetition."
        elif board.can_claim_fifty_moves():
            self.status_message = "Draw available — fifty-move rule."
        elif board.is_check():
            self.status_message = "Check!"
        else:
            self.status_message = ""

    def maybe_ai_move(self):
        if self.app_mode != "play":
            return
        if self.hazards.king_lost_color is not None:
            return   # game already ended via a hazard
        board = self.engine.board
        if board.is_game_over():
            return
        if board.turn == self.human_color:
            return
        self.status_message = "A.R.I.S.E. is thinking..."
        self._render()   # show the "thinking" status before the (blocking) search
        pygame.display.flip()

        move = self.ai.choose_move(board)
        if move is not None:
            self.engine.push_move(move)
            self.hazards.on_move_played(self.engine.board)
            self.game_clock.complete_move()
            self.game_clock.start_turn(self.engine.board.turn)
            self._check_game_over()

    def new_game(self):
        self.engine.new_game()
        self.app_mode = "play"
        self.selected_square = None
        self.legal_targets = []
        preset = CLOCK_PRESETS[self.clock_preset_index]
        self.game_clock.reset(preset[1], preset[2], preset[3])
        self.game_clock.start_turn(chess.WHITE)
        self.status_message = ""
        self.hazards.reset()   # fresh hazard timer, no leftover ice/black holes

    # ── Button dispatch ───────────────────────────────────────────────────

    def handle_button(self, action):
        if action == "new_game":
            self.new_game()

        elif action == "undo":
            self.engine.undo()
            if self.app_mode == "play":
                # also undo the AI reply if it was the AI's move on top, so the
                # human doesn't have to click undo twice for one "blunder"
                if self.engine.board.turn != self.human_color and self.engine.board.move_stack:
                    self.engine.undo()
            self.status_message = ""

        elif action == "redo":
            self.engine.redo()
            # symmetric redo of the AI move if one is queued
            if self.app_mode == "play" and self.engine.board.turn != self.human_color:
                self.engine.redo()

        elif action == "toggle_sandbox":
            if self.app_mode == "play":
                self.app_mode = "sandbox"
                self.engine.clear_board_for_editing()
                self.status_message = "Sandbox mode — click palette pieces, then click the board to place them."
            else:
                ok = self.engine.finalize_sandbox(turn=chess.WHITE)
                if ok:
                    self.app_mode = "play"
                    self.status_message = "Position applied — back to play mode."
                    self.game_clock.start_turn(self.engine.board.turn)
                else:
                    self.status_message = "Invalid position — each side needs exactly one king."

        elif action == "import_fen":
            self.fen_dialog_active = True
            self.fen_input.text = ""
            self.fen_input.active = True

        elif action == "export_fen":
            fen = self.engine.export_fen()
            if HAS_CLIPBOARD:
                try:
                    pyperclip.copy(fen)
                    self.status_message = "FEN copied to clipboard."
                except Exception:
                    self.status_message = f"FEN: {fen}"
            else:
                self.status_message = f"FEN: {fen}"
            print(f"[FEN] {fen}")

        elif action == "save_pgn":
            filename = f"arise_game_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pgn"
            if self.engine.save_pgn(filename):
                self.status_message = f"Saved {filename}"
            else:
                self.status_message = "Failed to save PGN."

        elif action == "cycle_theme":
            self.theme_index = (self.theme_index + 1) % len(THEME_ORDER)
            self.theme = THEMES[THEME_ORDER[self.theme_index]]
            self.btn_theme.label = f"Theme: {THEME_ORDER[self.theme_index]}"

        elif action == "cycle_clock":
            self.clock_preset_index = (self.clock_preset_index + 1) % len(CLOCK_PRESETS)
            preset = CLOCK_PRESETS[self.clock_preset_index]
            self.game_clock.reset(preset[1], preset[2], preset[3])
            self.game_clock.start_turn(self.engine.board.turn)
            self.btn_clock.label = f"Clock: {preset[0]}"

        elif action == "cycle_ai":
            idx = ChessAI.DIFFICULTIES.index(self.ai.difficulty)
            self.ai.difficulty = ChessAI.DIFFICULTIES[(idx + 1) % len(ChessAI.DIFFICULTIES)]
            self.btn_ai.label = f"Difficulty: {self.ai.difficulty}"

        elif action == "cycle_piece_style":
            idx = PIECE_STYLES.index(self.piece_style)
            self.piece_style = PIECE_STYLES[(idx + 1) % len(PIECE_STYLES)]
            self._piece_surface_cache.clear()   # old style's cached surfaces are stale
            self.btn_piece_style.label = f"Pieces: {PIECE_STYLE_LABELS[self.piece_style]}"

        elif action == "toggle_chaos":
            self.hazards.enabled = not self.hazards.enabled
            self.hazards.reset()   # restart the 5-ply timer fresh from now
            state_word = "ON" if self.hazards.enabled else "OFF"
            self.btn_chaos.label = f"Chaos Mode: {state_word}"
            if self.hazards.enabled:
                self.status_message = "Chaos Mode enabled — the board is now an enemy."
            else:
                self.status_message = "Chaos Mode disabled."

        elif action == "flip_board":
            self.white_at_bottom = not self.white_at_bottom

        elif action == "vision_mode":
            detect_chessboard()   # blocks until user presses Q, then returns here

    # ── Sandbox interactions ──────────────────────────────────────────────

    def handle_sandbox_click(self, pos):
        for entry in self.palette_buttons:
            if entry["rect"].collidepoint(pos):
                self.sandbox_selected_piece = (entry["piece_type"], entry["color"])
                return
        if self.eraser_rect.collidepoint(pos):
            self.sandbox_selected_piece = "erase"
            return

        square = screen_to_square(pos, self.white_at_bottom)
        if square is None:
            return
        if self.sandbox_selected_piece == "erase":
            self.engine.remove_piece(square)
        elif self.sandbox_selected_piece is not None:
            pt, color = self.sandbox_selected_piece
            self.engine.set_piece(square, chess.Piece(pt, color))

    # ── Event handling ────────────────────────────────────────────────────

    def handle_mouse_down(self, pos, button):
        if self.fen_dialog_active:
            return  # modal — ignore board/panel clicks while dialog is open

        if pos[0] >= BOARD_PIXELS:
            for b in self.buttons:
                if b.is_clicked(pos):
                    self.handle_button(b.action)
                    return
            if self.app_mode == "sandbox":
                self.handle_sandbox_click(pos)
            return

        if self.app_mode == "sandbox":
            self.handle_sandbox_click(pos)
            return

        if self.hazards.king_lost_color is not None:
            return   # game over via hazard — board is frozen, only panel buttons work

        # ── Play mode board click ────────────────────────────────────────
        square = screen_to_square(pos, self.white_at_bottom)
        if square is None:
            return

        if button == 1:  # left click
            if self.selected_square is not None and square in self.legal_targets:
                self.attempt_move(self.selected_square, square)
                self.maybe_ai_move()
                return

            piece = self.engine.board.piece_at(square)
            if piece and piece.color == self.engine.board.turn and piece.color == self.human_color:
                self.selected_square = square
                self.legal_targets = self.engine.legal_destinations(square)
                self.dragging = True
                self.drag_square = square
                self.drag_pos = pos
            else:
                self.selected_square = None
                self.legal_targets = []

    def handle_mouse_motion(self, pos):
        if self.dragging:
            self.drag_pos = pos

    def handle_mouse_up(self, pos, button):
        if self.dragging:
            if pos[0] < BOARD_PIXELS:
                target = screen_to_square(pos, self.white_at_bottom)
                if target is not None and target in self.legal_targets:
                    self.attempt_move(self.drag_square, target)
                    self.maybe_ai_move()
            self.dragging = False
            self.drag_square = None

    def handle_key(self, event):
        if self.fen_dialog_active:
            result = self.fen_input.handle_key(event)
            if result == "submit":
                if self.engine.import_fen(self.fen_input.text):
                    self.status_message = "FEN loaded."
                    self.game_clock.start_turn(self.engine.board.turn)
                else:
                    self.status_message = "Invalid FEN string."
                self.fen_dialog_active = False
                self.fen_input.active = False
            elif result == "cancel":
                self.fen_dialog_active = False
                self.fen_input.active = False

    # ── Rendering ─────────────────────────────────────────────────────────

    def _render_board(self):
        theme = self.theme
        last = self.engine.last_move()

        for square in chess.SQUARES:
            x, y = square_to_screen(square, self.white_at_bottom)
            is_light = (chess.square_rank(square) + chess.square_file(square)) % 2 == 1
            colour = theme["light"] if is_light else theme["dark"]
            pygame.draw.rect(self.screen, colour, (x, y, SQUARE, SQUARE))

            if last and square in (last.from_square, last.to_square):
                overlay = pygame.Surface((SQUARE, SQUARE), pygame.SRCALPHA)
                overlay.fill((*theme["last_move"], 110))
                self.screen.blit(overlay, (x, y))

            if square == self.selected_square:
                pygame.draw.rect(self.screen, theme["highlight"], (x, y, SQUARE, SQUARE), 4)

        # ── Chaos Mode hazard overlays ────────────────────────────────────
        if self.hazards.enabled:
            # Ice squares — pale cyan tint, darker the longer something has stood on it
            for sq, info in self.hazards.ice_squares.items():
                x, y = square_to_screen(sq, self.white_at_bottom)
                alpha = 70 + info["turns"] * 40   # gets more opaque as danger increases
                overlay = pygame.Surface((SQUARE, SQUARE), pygame.SRCALPHA)
                overlay.fill((140, 220, 255, min(alpha, 200)))
                self.screen.blit(overlay, (x, y))
                pygame.draw.rect(self.screen, (200, 240, 255), (x, y, SQUARE, SQUARE), 2)

            # Black holes — dark purple void with concentric rings
            for hole in self.hazards.black_holes:
                x, y = square_to_screen(hole["square"], self.white_at_bottom)
                cx, cy = x + SQUARE // 2, y + SQUARE // 2
                overlay = pygame.Surface((SQUARE, SQUARE), pygame.SRCALPHA)
                overlay.fill((30, 0, 40, 180))
                self.screen.blit(overlay, (x, y))
                pulse = (pygame.time.get_ticks() // 200) % 3
                for ring in range(3):
                    radius = SQUARE // 2 - ring * 10 - pulse * 3
                    if radius > 2:
                        pygame.draw.circle(self.screen, (170, 60, 220), (cx, cy), radius, 2)

        # Check flash on king square
        board = self.engine.board
        if board.is_check():
            king_sq = board.king(board.turn)
            if king_sq is not None:
                blink = (pygame.time.get_ticks() // 300) % 2 == 0
                if blink:
                    x, y = square_to_screen(king_sq, self.white_at_bottom)
                    overlay = pygame.Surface((SQUARE, SQUARE), pygame.SRCALPHA)
                    overlay.fill((*theme["check"], 140))
                    self.screen.blit(overlay, (x, y))

        # Legal destination dots
        for target in self.legal_targets:
            x, y = square_to_screen(target, self.white_at_bottom)
            centre = (x + SQUARE // 2, y + SQUARE // 2)
            is_capture = board.piece_at(target) is not None
            if is_capture:
                pygame.draw.circle(self.screen, theme["legal_dot"], centre, SQUARE // 2 - 4, 5)
            else:
                pygame.draw.circle(self.screen, theme["legal_dot"], centre, SQUARE // 8)

        # Pieces (skip the one currently being dragged — drawn separately on top)
        for square in chess.SQUARES:
            if self.dragging and square == self.drag_square:
                continue
            piece = board.piece_at(square)
            if piece:
                x, y = square_to_screen(square, self.white_at_bottom)
                surf = self.get_piece_surface(piece, SQUARE)
                self.screen.blit(surf, (x, y))

        if self.dragging and self.drag_square is not None:
            piece = board.piece_at(self.drag_square)
            if piece:
                px, py = self.drag_pos[0] - SQUARE // 2, self.drag_pos[1] - SQUARE // 2
                surf = self.get_piece_surface(piece, SQUARE)
                self.screen.blit(surf, (px, py))

        # Board border
        pygame.draw.rect(self.screen, theme["border"], (0, 0, BOARD_PIXELS, BOARD_PIXELS), 3)

    # ── Piece rendering — dispatches to one of 3 visual styles, cached ────

    def _get_font(self, kind: str, size: int):
        key = (kind, size)
        if key not in self._font_cache:
            if kind == "unicode":
                self._font_cache[key] = pygame.font.SysFont(
                    "segoeuisymbol,arial,dejavusans", int(size * 0.72))
            elif kind == "letter":
                self._font_cache[key] = pygame.font.SysFont(
                    "arial", int(size * 0.46), bold=True)
        return self._font_cache[key]

    def get_piece_surface(self, piece: chess.Piece, size: int) -> pygame.Surface:
        """Returns a cached, transparent size×size surface with the piece drawn
        in the currently selected visual style. Reused for the board, the
        dragged piece, and the sandbox palette swatches."""
        key = (self.piece_style, piece.symbol(), size)
        cached = self._piece_surface_cache.get(key)
        if cached is not None:
            return cached

        surf = pygame.Surface((size, size), pygame.SRCALPHA)
        if self.piece_style == "minimalist_vector":
            self._draw_vector_onto(surf, piece, size)
        elif self.piece_style == "letter_notation":
            self._draw_letter_onto(surf, piece, size)
        else:
            self._draw_unicode_onto(surf, piece, size)

        self._piece_surface_cache[key] = surf
        return surf

    def _draw_unicode_onto(self, surf: pygame.Surface, piece: chess.Piece, size: int):
        """Style 1 — classic Unicode chess glyphs with a thin outline for legibility."""
        font = self._get_font("unicode", size)
        symbol = UNICODE_PIECES[piece.symbol()]
        colour  = (255, 255, 255) if piece.color == chess.WHITE else (20, 20, 20)
        outline = (20, 20, 20)    if piece.color == chess.WHITE else (230, 230, 230)
        centre = (size // 2, size // 2)
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            o_txt = font.render(symbol, True, outline)
            o_rect = o_txt.get_rect(center=(centre[0] + dx, centre[1] + dy))
            surf.blit(o_txt, o_rect)
        txt = font.render(symbol, True, colour)
        surf.blit(txt, txt.get_rect(center=centre))

    def _draw_letter_onto(self, surf: pygame.Surface, piece: chess.Piece, size: int):
        """Style 2 — bold letter (K/Q/R/B/N/P) inside a coloured disc.
        Colour is conveyed by the disc, not by letter case, so it stays
        readable at small palette sizes too."""
        cx, cy = size // 2, size // 2
        r = size // 2 - max(2, size // 16)
        bg      = (248, 248, 248) if piece.color == chess.WHITE else (32, 32, 32)
        border  = (25, 25, 25)    if piece.color == chess.WHITE else (225, 225, 225)
        lettercol = (25, 25, 25)  if piece.color == chess.WHITE else (245, 245, 245)

        pygame.draw.circle(surf, bg, (cx, cy), r)
        pygame.draw.circle(surf, border, (cx, cy), r, 2)

        letters = {chess.PAWN: "P", chess.KNIGHT: "N", chess.BISHOP: "B",
                   chess.ROOK: "R", chess.QUEEN: "Q", chess.KING: "K"}
        font = self._get_font("letter", size)
        txt = font.render(letters[piece.piece_type], True, lettercol)
        surf.blit(txt, txt.get_rect(center=(cx, cy)))

    def _draw_vector_onto(self, surf: pygame.Surface, piece: chess.Piece, size: int):
        """Style 3 — flat geometric icons built from basic shapes, no font needed."""
        import math
        cx, cy = size // 2, size // 2
        r = size // 2 - max(3, size // 10)
        fg      = (250, 250, 250) if piece.color == chess.WHITE else (25, 25, 25)
        outline = (25, 25, 25)    if piece.color == chess.WHITE else (235, 235, 235)
        pt = piece.piece_type

        if pt == chess.PAWN:
            head_c = (cx, int(cy - r * 0.15))
            pygame.draw.circle(surf, fg, head_c, int(r * 0.55))
            pygame.draw.circle(surf, outline, head_c, int(r * 0.55), 2)
            base = pygame.Rect(0, 0, int(r * 1.3), int(r * 0.5))
            base.center = (cx, int(cy + r * 0.55))
            pygame.draw.rect(surf, fg, base, border_radius=int(r * 0.2))
            pygame.draw.rect(surf, outline, base, 2, border_radius=int(r * 0.2))

        elif pt == chess.KNIGHT:
            pts = [(cx - r * 0.5, cy + r * 0.7), (cx - r * 0.5, cy - r * 0.2),
                   (cx + r * 0.1, cy - r * 0.8), (cx + r * 0.6, cy - r * 0.5),
                   (cx + r * 0.15, cy - r * 0.15), (cx + r * 0.5, cy + r * 0.7)]
            pygame.draw.polygon(surf, fg, pts)
            pygame.draw.polygon(surf, outline, pts, 2)

        elif pt == chess.BISHOP:
            pts = [(cx, cy - r * 0.9), (cx + r * 0.55, cy + r * 0.3),
                   (cx, cy + r * 0.75), (cx - r * 0.55, cy + r * 0.3)]
            pygame.draw.polygon(surf, fg, pts)
            pygame.draw.polygon(surf, outline, pts, 2)
            pygame.draw.circle(surf, outline, (cx, int(cy - r * 0.9)), max(2, int(r * 0.08)))

        elif pt == chess.ROOK:
            body = pygame.Rect(0, 0, int(r * 1.3), int(r * 1.0))
            body.midbottom = (cx, int(cy + r * 0.85))
            pygame.draw.rect(surf, fg, body)
            pygame.draw.rect(surf, outline, body, 2)
            for i in range(3):
                mx = body.left + body.width * (i + 0.5) / 3
                merlon = pygame.Rect(0, 0, int(body.width / 3.4), int(r * 0.35))
                merlon.midbottom = (mx, body.top + 2)
                pygame.draw.rect(surf, fg, merlon)
                pygame.draw.rect(surf, outline, merlon, 2)

        elif pt == chess.QUEEN:
            pygame.draw.circle(surf, fg, (cx, cy), int(r * 0.75))
            pygame.draw.circle(surf, outline, (cx, cy), int(r * 0.75), 2)
            for ang_deg in (-90, -50, -10, -130, -170):
                ang = math.radians(ang_deg)
                tip = (cx + math.cos(ang) * r * 1.05, cy + math.sin(ang) * r * 1.05)
                tip_i = (int(tip[0]), int(tip[1]))
                pygame.draw.circle(surf, fg, tip_i, max(2, int(r * 0.13)))
                pygame.draw.circle(surf, outline, tip_i, max(2, int(r * 0.13)), 1)

        elif pt == chess.KING:
            body_c = (cx, int(cy + r * 0.1))
            pygame.draw.circle(surf, fg, body_c, int(r * 0.7))
            pygame.draw.circle(surf, outline, body_c, int(r * 0.7), 2)
            cross_v = pygame.Rect(0, 0, max(2, int(r * 0.16)), int(r * 0.55))
            cross_v.midbottom = (cx, int(cy - r * 0.35))
            cross_h = pygame.Rect(0, 0, int(r * 0.5), max(2, int(r * 0.16)))
            cross_h.center = (cx, int(cy - r * 0.55))
            pygame.draw.rect(surf, fg, cross_v)
            pygame.draw.rect(surf, outline, cross_v, 1)
            pygame.draw.rect(surf, fg, cross_h)
            pygame.draw.rect(surf, outline, cross_h, 1)

    def _render_panel(self):
        theme = self.theme
        panel_rect = pygame.Rect(BOARD_PIXELS, 0, PANEL_WIDTH, WINDOW_H)
        pygame.draw.rect(self.screen, theme["panel"], panel_rect)

        for b in self.buttons:
            b.draw(self.screen, self.font_small, theme)

        if self.app_mode == "sandbox":
            self._render_sandbox_palette()
        else:
            self._render_move_history()
            if self.hazards.enabled:
                self._render_hazard_log()
            self._render_clock()

    def _render_sandbox_palette(self):
        theme = self.theme
        y = self._panel_y_after_buttons
        label = self.font.render("Sandbox Palette", True, theme["text"])
        self.screen.blit(label, (BOARD_PIXELS + 16, y))

        for entry in self.palette_buttons:
            selected = self.sandbox_selected_piece == (entry["piece_type"], entry["color"])
            bg = theme["highlight"] if selected else theme["panel_btn"]
            pygame.draw.rect(self.screen, bg, entry["rect"], border_radius=4)
            pygame.draw.rect(self.screen, theme["border"], entry["rect"], 2, border_radius=4)

            piece_obj = chess.Piece(entry["piece_type"], entry["color"])
            swatch_size = entry["rect"].width - 4
            surf = self.get_piece_surface(piece_obj, swatch_size)
            self.screen.blit(surf, surf.get_rect(center=entry["rect"].center))

        eraser_selected = self.sandbox_selected_piece == "erase"
        bg = theme["highlight"] if eraser_selected else theme["panel_btn"]
        pygame.draw.rect(self.screen, bg, self.eraser_rect, border_radius=4)
        pygame.draw.rect(self.screen, theme["border"], self.eraser_rect, 2, border_radius=4)
        etxt = self.font_small.render("Erase", True, theme["text"])
        self.screen.blit(etxt, etxt.get_rect(center=self.eraser_rect.center))

        hint_y = self._sandbox_panel_bottom
        hint = self.font_small.render("Click 'Toggle Sandbox' again to apply.",
                                       True, theme["text"])
        self.screen.blit(hint, (BOARD_PIXELS + 16, hint_y))

    def _render_move_history(self):
        theme = self.theme
        y = self._panel_y_after_buttons
        label = self.font.render("Move History", True, theme["text"])
        self.screen.blit(label, (BOARD_PIXELS + 16, y))
        y += 28

        history = self.engine.san_history
        row_y = y
        # Leave extra room for the hazard log panel when Chaos Mode is active
        cutoff = WINDOW_H - 300 if self.hazards.enabled else WINDOW_H - 160
        for i in range(0, len(history), 2):
            move_no = i // 2 + 1
            white_move = history[i]
            black_move = history[i + 1] if i + 1 < len(history) else ""
            line = f"{move_no}. {white_move}  {black_move}"
            txt = self.font_small.render(line, True, theme["text"])
            self.screen.blit(txt, (BOARD_PIXELS + 16, row_y))
            row_y += 20
            if row_y > cutoff:
                # stop drawing once we'd overlap other panels; PGN export
                # still has the FULL history even if the panel can't show it
                break

    def _render_hazard_log(self):
        """Chaos Mode status panel — next-event countdown + recent hazard events."""
        theme = self.theme
        y = WINDOW_H - 230
        pygame.draw.line(self.screen, theme["border"],
                          (BOARD_PIXELS + 10, y - 8), (WINDOW_W - 10, y - 8), 2)

        header = self.font.render("Chaos Log", True, theme["check"])
        self.screen.blit(header, (BOARD_PIXELS + 16, y))
        y += 24

        interval = ChaosHazards.TRIGGER_INTERVAL
        remainder = self.hazards.ply_counter % interval
        next_in = interval - remainder if remainder != 0 else interval
        countdown = self.font_small.render(f"Next event in {next_in} ply", True, theme["text"])
        self.screen.blit(countdown, (BOARD_PIXELS + 16, y))
        y += 22

        for entry in self.hazards.log[-4:]:
            text = entry if len(entry) <= 44 else entry[:43] + "…"
            txt = self.font_small.render(text, True, theme["text"])
            self.screen.blit(txt, (BOARD_PIXELS + 16, y))
            y += 18

    def _render_clock(self):
        theme = self.theme
        y = WINDOW_H - 110
        pygame.draw.line(self.screen, theme["border"],
                          (BOARD_PIXELS + 10, y - 10), (WINDOW_W - 10, y - 10), 2)

        w_time = ChessClock.format_time(self.game_clock.get_display_time(chess.WHITE))
        b_time = ChessClock.format_time(self.game_clock.get_display_time(chess.BLACK))

        w_colour = theme["check"] if self.game_clock.is_flagged(chess.WHITE) else theme["text"]
        b_colour = theme["check"] if self.game_clock.is_flagged(chess.BLACK) else theme["text"]

        w_label = self.font.render(f"White: {w_time}", True, w_colour)
        b_label = self.font.render(f"Black: {b_time}", True, b_colour)
        self.screen.blit(w_label, (BOARD_PIXELS + 16, y))
        self.screen.blit(b_label, (BOARD_PIXELS + 16, y + 28))

    def _render_status_bar(self):
        theme = self.theme
        rect = pygame.Rect(0, BOARD_PIXELS, BOARD_PIXELS, WINDOW_H - BOARD_PIXELS)
        pygame.draw.rect(self.screen, theme["background"], rect)
        if self.status_message:
            txt = self.font.render(self.status_message, True, theme["text"])
            self.screen.blit(txt, (10, BOARD_PIXELS + 8))

    def _render_fen_dialog(self):
        overlay = pygame.Surface((WINDOW_W, WINDOW_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.screen.blit(overlay, (0, 0))

        box_rect = pygame.Rect(30, WINDOW_H // 2 - 60, BOARD_PIXELS - 60, 130)
        pygame.draw.rect(self.screen, (240, 240, 240), box_rect, border_radius=8)
        pygame.draw.rect(self.screen, (20, 20, 20), box_rect, 3, border_radius=8)

        title = self.font_big.render("Import FEN", True, (20, 20, 20))
        self.screen.blit(title, (box_rect.x + 16, box_rect.y + 10))

        hint = self.font_small.render("Paste/type a FEN string, press Enter to load, Esc to cancel.",
                                       True, (60, 60, 60))
        self.screen.blit(hint, (box_rect.x + 16, box_rect.y + 46))

        self.fen_input.rect.x = box_rect.x + 16
        self.fen_input.rect.y = box_rect.y + 74
        self.fen_input.rect.width = box_rect.width - 32
        self.fen_input.draw(self.screen)

    def _render(self):
        self.screen.fill(self.theme["background"])
        self._render_board()
        self._render_panel()
        self._render_status_bar()
        if self.fen_dialog_active:
            self._render_fen_dialog()

    # ── Main loop ─────────────────────────────────────────────────────────

    def run(self):
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    self.handle_mouse_down(event.pos, event.button)
                elif event.type == pygame.MOUSEMOTION:
                    self.handle_mouse_motion(event.pos)
                elif event.type == pygame.MOUSEBUTTONUP:
                    self.handle_mouse_up(event.pos, event.button)
                elif event.type == pygame.KEYDOWN:
                    self.handle_key(event)

            # Flag check (out of time)
            if self.app_mode == "play" and not self.engine.board.is_game_over():
                if self.game_clock.is_flagged(chess.WHITE):
                    self.status_message = "White flagged — Black wins on time."
                elif self.game_clock.is_flagged(chess.BLACK):
                    self.status_message = "Black flagged — White wins on time."

            self._render()
            pygame.display.flip()
            self.clock_tick.tick(60)

        pygame.quit()


if __name__ == "__main__":
    app = AriseApp()
    app.run()
