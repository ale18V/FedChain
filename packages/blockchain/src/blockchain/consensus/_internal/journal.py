from typing import Iterable, Optional
from blockchain.models import Commit, Vote, Message
from blockchain.generated import peer_pb2
from ...utils import get_tx_hash


class MessageLog:
    prevotes: dict[int, set[Vote]]
    precommits: dict[int, set[Commit]]
    proposals: dict[bytes, peer_pb2.Block]

    def __init__(self) -> None:
        self.prevotes = {}
        self.precommits = {}
        self.proposals = {}
        self.tx_whitelist: dict[int, dict[bytes, int]] = {}
        self.tx_blacklist: dict[int, dict[bytes, int]] = {}

    def count_prevotes(self, round: int) -> int:
        return len(self.prevotes.get(round, []))

    def count_precommits(self, round: int) -> int:
        return len(self.precommits.get(round, []))

    def count_prevotes_for(self, round: int, hash: bytes | None) -> int:
        return len(list(filter(lambda vote: vote.target == hash, self.prevotes.get(round, []))))

    def count_precommits_for(self, round: int, hash: bytes | None) -> int:
        return len(list(filter(lambda commit: commit.target == hash, self.precommits.get(round, []))))

    def add_message(self, message: Message) -> bool:
        if isinstance(message, peer_pb2.PrecommitMessage):
            return self.add_precommit(message)
        elif isinstance(message, peer_pb2.PrevoteMessage):
            return self.add_prevote(message)
        elif isinstance(message, peer_pb2.ProposeBlockRequest):
            return self.add_proposal(message)

    def get_candidate(self, hash: bytes) -> Optional[peer_pb2.Block]:
        return self.proposals.get(hash, None)

    def add_precommit(self, precommit: peer_pb2.PrecommitMessage) -> bool:
        if precommit.round not in self.precommits:
            self.precommits[precommit.round] = set()
        commit = Commit(precommit.pubkey, precommit.hash)
        if commit in self.precommits[precommit.round]:
            return False

        self.precommits[precommit.round].add(commit)
        return True

    def add_prevote(self, prevote: peer_pb2.PrevoteMessage) -> bool:
        if prevote.round not in self.prevotes:
            self.prevotes[prevote.round] = set()
            self.tx_whitelist[prevote.round] = {}
            self.tx_blacklist[prevote.round] = {}

        vote = Vote(prevote.pubkey, prevote.hash)
        if vote in self.prevotes[prevote.round]:
            return False

        block = self.get_candidate(prevote.hash)
        bad_txs = set(prevote.invalid_txs)
        for tx in bad_txs:
            if tx not in self.tx_blacklist[prevote.round]:
                self.tx_blacklist[prevote.round][tx] = 0
            self.tx_blacklist[prevote.round][tx] += 1

        if block:
            good_txs = set(map(lambda tx: get_tx_hash(tx), block.body.transactions)) - bad_txs
            for txid in good_txs:
                if txid not in self.tx_whitelist[prevote.round]:
                    self.tx_whitelist[prevote.round][txid] = 0

                if txid not in prevote.invalid_txs:
                    self.tx_whitelist[prevote.round][txid] += 1

        self.prevotes[prevote.round].add(Vote(prevote.pubkey, prevote.hash))
        return True

    def add_proposal(self, proposal: peer_pb2.ProposeBlockRequest) -> bool:
        hash = proposal.block.header.hash
        if hash in self.proposals:
            return False

        self.proposals[proposal.block.header.hash] = proposal.block
        return True

    def has_precommit_quorum(self, round: int, target: Optional[bytes], threshold: int) -> bool:
        return self.count_precommits_for(round, target) >= threshold

    def has_prevote_quorum(self, round: int, target: Optional[bytes], threshold: int) -> bool:
        return self.count_prevotes_for(round, target) >= threshold

    def get_invalid_txs(self, round: int, threshold: int) -> Iterable[bytes]:
        return map(lambda x: x[0], filter(lambda x: x[1] >= threshold, self.tx_blacklist.get(round, {}).items()))

    def get_valid_txs(self, round: int, threshold: int) -> Iterable[bytes]:
        return map(lambda x: x[0], filter(lambda x: x[1] >= threshold, self.tx_whitelist.get(round, {}).items()))

    def reset(self) -> None:
        self.prevotes = {}
        self.precommits = {}
        self.proposals = {}
        self.tx_whitelist = {}
        self.tx_blacklist = {}
