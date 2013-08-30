import psycopg2 as pg
import psycopg2.extensions
psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)
import pywikibot as wp


from . import const, settings
from urlparse import urlparse


WIKI_PREFIX = "/wiki/"


db = None


class IsDisambigPage(Exception):
    pass


def setup_db(processed_table_query, create_table):
    global db
    db = pg.connect(settings.connection_string)
    db.autocommit = True
    if create_table:
        cur = db.cursor()
        cur.execute("SET search_path TO musicbrainz")
        cur.execute(processed_table_query)
        db.commit()


def get_entities_with_wikilinks(query, limit):
    cur = db.cursor()
    cur.execute(query, (limit,))
    return cur


def get_wikidata_itempage_from_wikilink(wikilink):
    """Given a link to a wikipedia page, retrieve its page on Wikidata"""
    parsed_url = urlparse(wikilink)
    pagename = parsed_url.path.replace(WIKI_PREFIX, "")
    wikilanguage = parsed_url.netloc.split(".")[0]
    wikisite = wp.Site(wikilanguage, "wikipedia")
    enwikipage = wp.Page(wikisite, pagename)
    if enwikipage.isDisambig():
        raise IsDisambigPage()
    wikidatapage = wp.ItemPage.fromPage(enwikipage)
    try:
        wikidatapage.get()
    except wp.NoPage as e:
        return None
    return wikidatapage


def add_mbid_claim_to_item(pid, item, mbid, donefunc, simulate=False):
    """
    Adds a claim with pid `pid` with value `mbid` to `item` and call `donefunc`
    with `mbid` to signal the completion.

    :type pid: str
    :type mbid: str
    :type item: pywikibot.ItemPage
    """
    claim = wp.Claim(const.WIKIDATA_DATASITE, pid)
    claim.setTarget(mbid)
    wp.output(u"Adding property {pid}, value {mbid} to {title}".format
              (pid=pid, mbid=mbid, title=item.title()))
    if simulate:
        wp.output("Simulation, no property has been added")
        return
    try:
        item.addClaim(claim, True)
    except wp.UserBlocked as e:
        wp.error("I have been blocked")
        exit(1)
    except wp.Error as e:
        wp.warning(e)
        return
    else:
        wp.output("Adding the source Claim")
        claim.addSource(const.MUSICBRAINZ_CLAIM, bot=True)
        donefunc(mbid)


def mainloop(pid, create_processed_table_query, wiki_entity_query, donefunc):
    create_table = False
    simulate = False
    limit = None

    for arg in wp.handleArgs():
        if arg == '-dryrun':
            simulate = True
        elif arg.startswith('-limit'):
            limit = int(arg[len('-limit:'):])
        elif arg == "-createtable":
            create_table = True

    const.WIKIDATA.login()
    const.MUSICBRAINZ_CLAIM.setTarget(const.MUSICBRAINZ_WIKIDATAPAGE)
    setup_db(create_processed_table_query, create_table)
    results = get_entities_with_wikilinks(wiki_entity_query, limit)

    if results.rowcount == 0:
        wp.output("No more unprocessed entries in MB")
        exit(0)

    for index, (mbid, wikipage) in enumerate(results):
        try:
            itempage = get_wikidata_itempage_from_wikilink(wikipage)
        except wp.NoSuchSite:
            wp.output("{page} no supported family".format(page=wikipage))
            continue
        except IsDisambigPage:
            wp.output("{page} is a disambiguation page".format(page=wikipage))
            continue
        if itempage is None:
            wp.debug(u"There's no wikidata page for {mbid}".format(mbid=mbid),
                    layer="")
            continue

        if any(key.lower() == pid.lower() for key in itempage.claims.keys()):
            wp.output(u"{mbid} already has property {pid}".format(mbid=mbid,
                                                                     pid=pid))
            donefunc(mbid)
            continue

        wp.output("{mbid} is not linked in in Wikidata".format(
                    mbid=mbid))
        add_mbid_claim_to_item(pid, itempage, mbid, donefunc, simulate)
