"""Negative filters: drop promo/shill, competitor marketing, hateful content,
and posts that are simply not about crypto trading at all.

No real slurs appear in this file. The hate-term mechanism is exercised with
placeholder vocabulary; the operator supplies the real list privately.
"""
import os
import unittest

from reply_pipeline.veto import Veto

try:
    import yaml
except ImportError:                                   # pragma: no cover
    yaml = None

_CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "config.example.yaml")


def _veto(**kw):
    kw.setdefault("domain_terms", ["solana", "memecoin", "token", "wallet", "pump"])
    return Veto(**kw)


class TestHateFilter(unittest.TestCase):
    def test_hate_term_is_vetoed(self):
        v = _veto(hate_terms=["badword"], require_domain=False)
        hit = v.check("these badword people should not be here")
        self.assertIsNotNone(hit)
        self.assertEqual(hit[0], "hate")

    def test_matching_is_word_bounded(self):
        # The Scunthorpe problem: substring matching flags innocent words that
        # merely contain a blocked term.
        v = _veto(hate_terms=["ass"], require_domain=False)
        self.assertIsNone(v.check("i missed the pump, need a class of tools to pass on rugs"))
        self.assertIsNotNone(v.check("you ass"))

    def test_hate_beats_every_other_category(self):
        # A slur-posting account that also reads as a lead must still be dropped.
        v = _veto(hate_terms=["badword"])
        hit = v.check("badword — anyway how do i find solana gems early?")
        self.assertEqual(hit[0], "hate")

    def test_case_insensitive(self):
        v = _veto(hate_terms=["badword"], require_domain=False)
        self.assertIsNotNone(v.check("BadWord"))


class TestPromoFilter(unittest.TestCase):
    def test_promo_marker_is_vetoed(self):
        v = _veto(promo_markers=["dm me", "presale"])
        hit = v.check("solana presale live now, dont miss the next token")
        self.assertEqual(hit[0], "promo")

    def test_evm_contract_address_is_vetoed(self):
        v = _veto()
        hit = v.check("aped this solana token 0x52908400098527886E0F7030069857D2E4169EE7 lfg")
        self.assertEqual(hit[0], "promo")

    def test_telegram_invite_is_vetoed(self):
        v = _veto()
        self.assertEqual(v.check("solana calls in t.me/somechannel")[0], "promo")

    def test_a_genuine_lead_is_not_promo(self):
        v = _veto(promo_markers=["dm me", "presale"])
        self.assertIsNone(v.check("how do you guys find these solana gems before they pump?"))


class TestCompetitorFilter(unittest.TestCase):
    def test_competitor_product_mention_is_vetoed(self):
        v = _veto(competitor_markers=["rivalscan"])
        hit = v.check("just use rivalscan for your solana wallet tracking")
        self.assertEqual(hit[0], "competitor")

    def test_first_person_selling_is_vetoed(self):
        v = _veto(competitor_markers=["we built"])
        hit = v.check("we built a solana wallet tracker, free beta")
        self.assertEqual(hit[0], "competitor")


class TestDomainGate(unittest.TestCase):
    def test_off_topic_medical_post_is_vetoed(self):
        # The real failure: "best bot" matched a cancer update.
        v = _veto(require_domain=True)
        hit = v.check("mums scan came back clear, best bot of news all year")
        self.assertEqual(hit[0], "off_topic")

    def test_unrelated_software_question_is_vetoed(self):
        v = _veto(require_domain=True)
        hit = v.check("what tool do you use for kubernetes log aggregation?")
        self.assertEqual(hit[0], "off_topic")

    def test_in_domain_post_passes(self):
        v = _veto(require_domain=True)
        self.assertIsNone(v.check("what tool do you use to track solana wallets?"))

    def test_cashtag_counts_as_domain_signal(self):
        v = _veto(require_domain=True)
        self.assertIsNone(v.check("wish i aped $WIF earlier, always too late"))

    def test_domain_gate_off_by_default(self):
        v = _veto(require_domain=False)
        self.assertIsNone(v.check("what tool do you use for kubernetes logs?"))


class TestAnnouncementFilter(unittest.TestCase):
    def test_launch_announcement_is_vetoed(self):
        v = _veto(announcement_markers=["just launched", "now live"])
        hit = v.check("just launched our solana scanner, now live")
        self.assertEqual(hit[0], "announcement")

    def test_gain_brag_is_vetoed_without_any_word_list(self):
        # No marker matches "up 40x" — a bare number is the whole tell.
        v = _veto()
        self.assertEqual(v.check("up 40x on that solana play")[0], "announcement")
        self.assertEqual(v.check("did 300% on my solana bag")[0], "announcement")

    def test_victory_lap_about_own_call_is_vetoed(self):
        v = _veto()
        self.assertEqual(v.check("20x from my call on solana")[0], "announcement")

    def test_a_lead_mentioning_a_multiple_is_not_an_announcement(self):
        # "missed another 10x" is regret, not a brag: no gain verb precedes it.
        v = _veto()
        self.assertIsNone(v.check("missed another 10x solana runner again smh"))


class TestAskGate(unittest.TestCase):
    def test_question_passes(self):
        v = _veto(require_ask=True)
        self.assertIsNone(v.check("how do you find these solana gems early?"))

    def test_statement_without_any_ask_is_vetoed(self):
        v = _veto(require_ask=True)
        self.assertEqual(v.check("solana pumping hard right now")[0], "not_asking")

    def test_first_person_pain_counts_as_asking(self):
        # The Regret/FOMO themes never ask anything outright, and are the
        # highest-intent replies in the sheet.
        v = _veto(require_ask=True)
        self.assertIsNone(v.check("wish i aped that solana runner earlier"))
        self.assertIsNone(v.check("i keep missing these solana pumps"))

    def test_pain_without_a_pronoun_still_counts(self):
        v = _veto(require_ask=True)
        self.assertIsNone(v.check("missed another solana runner again smh"))

    def test_third_person_commentary_is_not_asking(self):
        # Identical pain vocabulary, but the author is a spectator, not a buyer.
        v = _veto(require_ask=True)
        self.assertEqual(v.check("he keeps missing these solana runners lol")[0],
                         "not_asking")
        self.assertEqual(v.check("everyone fumbled that solana bag today")[0],
                         "not_asking")

    def test_typod_pain_survives_because_matching_is_fuzzy(self):
        # Theme matching is fuzzy; an exact-match gate in front of it would
        # delete exactly the leads the fuzzy layer exists to catch.
        v = _veto(require_ask=True)
        self.assertIsNone(v.check("missd anethr solana runner ugh"))

    def test_gate_is_off_unless_requested(self):
        v = _veto(require_ask=False)
        self.assertIsNone(v.check("solana pumping hard right now"))

    def test_ask_markers_widen_the_builtin_patterns(self):
        v = _veto(require_ask=True, ask_markers=["am i cooked"])
        self.assertIsNone(v.check("am i cooked on this solana bag"))
        # ...without discarding the built-ins.
        self.assertIsNone(v.check("how do i find solana gems early?"))

    def test_hate_still_beats_a_perfectly_phrased_ask(self):
        v = _veto(hate_terms=["badword"], require_ask=True)
        self.assertEqual(v.check("badword — how do i find solana gems?")[0], "hate")


class TestHateFilterVisibility(unittest.TestCase):
    def test_absent_hate_list_is_reportable(self):
        # Shipping an empty list is deliberate; silently doing nothing is not.
        self.assertFalse(Veto().has_hate_filter)

    def test_configured_hate_list_reports_active(self):
        self.assertTrue(Veto(hate_terms=["badword"]).has_hate_filter)


class TestConstruction(unittest.TestCase):
    def test_empty_config_vetoes_nothing(self):
        self.assertIsNone(Veto().check("literally anything at all"))

    def test_from_config_reads_the_veto_block(self):
        cfg = {"veto": {"promo_markers": ["presale"]},
               "require_domain": True,
               "domain_terms": ["solana"]}
        v = Veto.from_config(cfg)
        self.assertEqual(v.check("solana presale now")[0], "promo")
        self.assertEqual(v.check("what tool for kubernetes?")[0], "off_topic")

    def test_from_config_tolerates_a_missing_veto_block(self):
        self.assertIsNone(Veto.from_config({}).check("anything"))

    def test_blank_text_is_not_vetoed(self):
        self.assertIsNone(_veto(require_domain=True).check(""))


@unittest.skipIf(yaml is None, "PyYAML not installed")
class TestShippedConfigDoesNotOverFilter(unittest.TestCase):
    """The domain gate must not reject genuine leads.

    Real buying intent is often phrased in pure community slang with no explicit
    crypto noun in it ("find these gems before they run"). A domain vocabulary
    that misses that silently deletes the best leads in the sheet, which is a
    worse failure than letting a little noise through — the LLM gate is the
    second layer for the noise, but nothing recovers a lead vetoed at stage 1.
    """

    ARCHETYPAL_LEADS = [
        "how do you guys find these gems early before they run?",
        "anyone know a good tool to track whale wallets on solana?",
        "wish i bought $ANSEM earlier honestly",
        "missed another 10x again smh",
        "missd anethr runner ugh",
        "how to find early coins",
        "keep getting rugged, sick of paid callers",
        "im always too late to the runners, whats everyone using",
        "new to the trenches, where do i start?",
        "fumbled the bag again, need a better way to catch these early",
    ]

    OUT_OF_UNIVERSE = [
        "mums scan came back clear today, best bot of news all year",
        "whats the best bot or tool you use for kubernetes log aggregation?",
        "any tool recommendations for editing podcast audio?",
    ]

    @classmethod
    def setUpClass(cls):
        with open(_CONFIG, encoding="utf-8") as f:
            cls.cfg = yaml.safe_load(f)
        cls.veto = Veto.from_config(cls.cfg)

    ANNOUNCEMENTS = [
        "just launched our new solana scanner, now live",
        "called it again, up 40x on that solana play",
        "took profits on that runner, easy money lfg",
        "my last call did 300% on solana",
    ]

    NOT_ASKING = [
        "he keeps missing these solana runners lol",
        "everyone fumbled that solana bag today",
        "solana pumping hard right now",
    ]

    def test_domain_gate_is_actually_enabled_in_the_shipped_config(self):
        self.assertTrue(self.veto.require_domain)

    def test_ask_gate_is_actually_enabled_in_the_shipped_config(self):
        self.assertTrue(self.veto.require_ask)

    def test_announcements_are_vetoed(self):
        for text in self.ANNOUNCEMENTS:
            with self.subTest(text=text):
                hit = self.veto.check(text)
                self.assertIsNotNone(hit)
                self.assertEqual(hit[0], "announcement")

    def test_broadcasting_and_commentary_are_vetoed(self):
        for text in self.NOT_ASKING:
            with self.subTest(text=text):
                hit = self.veto.check(text)
                self.assertIsNotNone(hit)
                self.assertEqual(hit[0], "not_asking")

    def test_genuine_leads_survive(self):
        for text in self.ARCHETYPAL_LEADS:
            with self.subTest(text=text):
                self.assertIsNone(self.veto.check(text))

    def test_out_of_universe_posts_are_vetoed(self):
        for text in self.OUT_OF_UNIVERSE:
            with self.subTest(text=text):
                hit = self.veto.check(text)
                self.assertIsNotNone(hit)
                self.assertEqual(hit[0], "off_topic")


if __name__ == "__main__":
    unittest.main()
