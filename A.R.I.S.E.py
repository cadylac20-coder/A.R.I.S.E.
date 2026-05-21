import random
import chess
import cv2
import numpy as np

import chess.engine

#Chess Board
board = chess.Board()

# Example move
move = chess.Move.from_uci("e2e4")
board.push(move)

print(board)

# Basic AI that picks random moves
class SimpleChessAI:
    def __init__(self):
        self.board = chess.Board()

    def make_ai_move(self):
        # List all legal moves
        legal_moves = list(self.board.legal_moves)
        # Pick a random legal move
        move = random.choice(legal_moves)
        self.board.push(move)
        print(f"AI plays: {move}")

    def make_human_move(self, move_uci):
        try:
            move = chess.Move.from_uci(move_uci)
            if move in self.board.legal_moves:
                self.board.push(move)
            else:
                print("Illegal move.")
        except:
            print("Invalid move format. Use UCI format like 'e2e4'.")

    def play(self):
        print("Game Start!")
        print(self.board)

        while not self.board.is_game_over():
            # Human Move
            human_move = input("Your move (e.g., e2e4): ")
            self.make_human_move(human_move)
            print(self.board)

            if self.board.is_game_over():
                break

            # AI Move
            self.make_ai_move()
            print(self.board)

        print("Game Over!")
        print("Result:", self.board.result())

# Create and start the game
game = SimpleChessAI()
game.play()


def detect_chessboard():
    cap = cv2.VideoCapture(0)  # 0 is usually the default webcam

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Convert to grayscale for easier processing
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Try to find a chessboard pattern (7x7 grid for example)
        board_size = (7, 7)
        ret, corners = cv2.findChessboardCorners(gray, board_size, None)

        if ret:
            # If found, draw the corners
            cv2.drawChessboardCorners(frame, board_size, corners, ret)
            cv2.putText(frame, "Chessboard detected", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        
        # Show the frame
        cv2.imshow('Chess Vision - SEVAGOTH', frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

detect_chessboard()