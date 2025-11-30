import re
from dataclasses import dataclass


@dataclass
class ManaPool:
    W: int = 0
    U: int = 0
    B: int = 0
    R: int = 0
    G: int = 0
    C: int = 0

    @property
    def total(self) -> int:
        return self.W + self.U + self.B + self.R + self.G + self.C

    def to_dict(self) -> dict:
        _dict =  {
            "W": self.W,
            "U": self.U,
            "B": self.B,
            "R": self.R,
            "G": self.G,
            "C": self.C,
        }
        _dict = {k: v for k, v in _dict.items() if v != 0}
        return _dict
    
    def to_list_tuple(self) -> list[tuple[str, int]]:
        # remove colors with 0 count
        return list((color, getattr(self, color)) for color in ["W", "U", "B", "R", "G", "C"] if getattr(self, color) > 0)
        
    
    def can_pay(self, cost: "ManaCost") -> bool:
        remaining = self.total

        for color in ["W", "U", "B", "R", "G"]:
            required = getattr(cost, color)
            available = getattr(self, color)
            if available < required:
                return False
            remaining -= required

        if self.C < cost.C:
            return False
        remaining -= cost.C

        return remaining >= cost.generic


@dataclass
class ManaCost:
    W: int = 0
    U: int = 0
    B: int = 0
    R: int = 0
    G: int = 0
    C: int = 0
    generic: int = 0

    @classmethod
    def from_string(cls, mana_cost: str) -> "ManaCost":
        if not mana_cost:
            return cls()

        cost = cls()
        symbols = re.findall(r"\{([^}]+)}", mana_cost)

        for symbol in symbols:
            if symbol.isdigit():
                cost.generic += int(symbol)
            elif symbol == "W":
                cost.W += 1
            elif symbol == "U":
                cost.U += 1
            elif symbol == "B":
                cost.B += 1
            elif symbol == "R":
                cost.R += 1
            elif symbol == "G":
                cost.G += 1
            elif symbol == "C":
                cost.C += 1
            elif symbol == "X":
                pass
            elif "/" in symbol:
                colors = symbol.split("/")
                if "P" in colors:
                    color = [c for c in colors if c != "P"][0]
                    setattr(cost, color, getattr(cost, color) + 1)
                else:
                    if colors[0].isdigit():
                        cost.generic += int(colors[0])
                    else:
                        setattr(cost, colors[0], getattr(cost, colors[0]) + 1)

        return cost