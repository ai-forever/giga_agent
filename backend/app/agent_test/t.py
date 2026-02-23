from functools import cache

from pydantic import BaseModel, Field


class User(BaseModel):
    user_id: int

    def __hash__(self):
        return hash(frozenset({"user_id": self.user_id}.items()))


@cache
def rr(user: User):
    print("call")
    return user.user_id


usr = User(user_id=1)
print(rr(usr))
usr.user_id = 2
print(rr(usr))
print(rr(usr))
