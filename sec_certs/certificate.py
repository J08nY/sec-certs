from datetime import datetime, date
from dataclasses import dataclass
import logging
from . import helpers
from abc import ABC, abstractmethod
from bs4 import Tag
from typing import Union, Optional


class Certificate(ABC):
    def __init__(self):
        pass

    def __repr__(self) -> str:
        return str(self.to_dict())

    def __str__(self) -> str:
        return 'Not implemented'

    @property
    @abstractmethod
    def dgst(self):
        raise NotImplementedError('Not meant to be implemented')

    @abstractmethod
    def to_dict(self) -> dict:
        raise NotImplementedError('Not meant to be implemented')

    def __eq__(self, other: 'Certificate') -> bool:
        return self.dgst == other.dgst

    @classmethod
    @abstractmethod
    def from_dict(cls, dct: dict) -> 'Certificate':
        raise NotImplementedError('Mot meant to be implemented')

    @abstractmethod
    def merge(self, other: 'Certificate'):
        raise NotImplementedError('Not meant to be implemented')


class FIPSCertificate(Certificate):
    def to_dict(self) -> dict:
        pass

    @classmethod
    def from_dict(cls, dct: dict) -> 'FIPSCertificate':
        return FIPSCertificate()

    @property
    def dgst(self):
        return None  # TODO: Implement me


class CommonCriteriaCert(Certificate):
    cc_url = 'http://www.commoncriteriaportal.org'

    @dataclass(eq=True, frozen=True)
    class MaintainanceReport:
        """
        Object for holding maintainance reports.
        """
        maintainance_date: date
        maintainance_title: str
        maintainance_report_link: str
        maintainance_st_link: str

        def __post_init__(self):
            super().__setattr__('maintainance_report_link', helpers.sanitize_link(self.maintainance_report_link))
            super().__setattr__('maintainance_st_link', helpers.sanitize_link(self.maintainance_st_link))
            super().__setattr__('maintainance_title', helpers.sanitize_string(self.maintainance_title))
            super().__setattr__('maintainance_date', helpers.sanitize_date(self.maintainance_date))

        def to_dict(self):
            return self.__dict__

    @dataclass(eq=True, frozen=True)
    class ProtectionProfile:
        """
        Object for holding protection profiles.
        """
        name: str
        link: Optional[str]

        def __post_init__(self):
            super().__setattr__('name', helpers.sanitize_string(self.name))
            super().__setattr__('link', helpers.sanitize_link(self.link))

        def to_dict(self):
            return self.__dict__

    def __init__(self, category: str, name: str, manufacturer: str, scheme: str,
                 security_level: Union[str, set], not_valid_before: date,
                 not_valid_after: date, report_link: str, st_link: str, src: str, cert_link: Optional[str],
                 manufacturer_web: Optional[str],
                 protection_profiles: set,
                 maintainance_updates: set):
        super().__init__()

        self.category = category
        self.name = helpers.sanitize_string(name)
        self.manufacturer = helpers.sanitize_string(manufacturer)
        self.scheme = scheme
        self.security_level = helpers.sanitize_security_levels(security_level)
        self.not_valid_before = helpers.sanitize_date(not_valid_before)
        self.not_valid_after = helpers.sanitize_date(not_valid_after)
        self.report_link = helpers.sanitize_link(report_link)
        self.st_link = helpers.sanitize_link(st_link)
        self.src = src
        self.cert_link = helpers.sanitize_link(cert_link)
        self.manufacturer_web = helpers.sanitize_link(manufacturer_web)
        self.protection_profiles = protection_profiles
        self.maintainances = maintainance_updates

    @property
    def dgst(self) -> str:
        """
        Computes the primary key of the certificate using first 16 bytes of SHA-256 digest
        """
        return helpers.get_first_16_bytes_sha256(self.category + self.name + self.report_link)

    def merge(self, other: 'CommonCriteriaCert'):
        """
        Merges with other CC certificate. Assuming they come from different sources, e.g., csv and html.
        Assuming that html source has better protection profiles, they overwrite CSV info
        On other values (apart from maintainances, see TODO below) the sanity checks are made.
        """
        if self != other:
            logging.warning(f'Attempting to merge divergent certificates: self[dgst]={self.dgst}, other[dgst]={other.dgst}')

        for att, val in vars(self).items():
            if not val:
                setattr(self, att, getattr(other, att))
            elif self.src == 'csv' and other.src == 'html' and att == 'protection_profiles':
                setattr(self, att, getattr(other, att))
            elif att == 'maintainances':
                # TODO Fix me: This is a simplification. Basically take the longer list of maintainances as a ground truth.
                if len(getattr(self, att)) < len(getattr(other, att)):
                    setattr(self, att, getattr(other, att))
            elif att == 'src':
                pass  # This is expected
            else:
                if getattr(self, att) != getattr(other, att):
                    logging.warning(f'When merging certificates with dgst {self.dgst}, the following mismatch occured: Attribute={att}, self[{att}]={getattr(self, att)}, other[{att}]={getattr(other, att)}')
        if self.src != other.src:
            self.src = self.src + ' + ' + other.src

    def to_dict(self) -> dict:
        return self.__dict__

    @classmethod
    def from_dict(cls, dct: dict) -> 'CommonCriteriaCert':
        # TODO: Implement me
        pass

    @classmethod
    def from_html_row(cls, row: Tag, category: str) -> 'CommonCriteriaCert':
        """
        Creates a CC certificate from html row
        """
        def get_name(cell: Tag) -> str:
            return list(cell.stripped_strings)[0]

        def get_manufacturer(cell: Tag) -> Optional[str]:
            if lst := list(cell.stripped_strings):
                return lst[0]
            else:
                return None

        def get_scheme(cell: Tag) -> str:
            return list(cell.stripped_strings)[0]

        def get_security_level(cell: Tag) -> set:
            return set(cell.stripped_strings)

        def get_manufacturer_web(cell: Tag) -> Optional[str]:
            for link in cell.find_all('a'):
                if link is not None and link.get('title') == 'Vendor\'s web site' and link.get('href') != 'http://':
                   return link.get('href')
            return None

        def get_protection_profiles(cell: Tag) -> set:
            protection_profiles = set()
            for link in list(cell.find_all('a')):
                if link.get('href') is not None and '/ppfiles/' in link.get('href'):
                    protection_profiles.add(CommonCriteriaCert.ProtectionProfile(str(link.contents[0]), CommonCriteriaCert.cc_url + link.get('href')))
            return protection_profiles

        def get_date(cell: Tag) -> date:
            text = cell.get_text()
            extracted_date = datetime.strptime(text, '%Y-%m-%d').date() if text else None
            return extracted_date

        def get_report_st_links(cell: Tag) -> (str, str):
            links = cell.find_all('a')
            # TODO: Exception checks
            assert links[1].get('title').startswith('Certification Report')
            assert links[2].get('title').startswith('Security Target')

            report_link = CommonCriteriaCert.cc_url + links[1].get('href')
            security_target_link = CommonCriteriaCert.cc_url + links[2].get('href')

            return report_link, security_target_link

        def get_cert_link(cell: Tag) -> Optional[str]:
            links = cell.find_all('a')
            return CommonCriteriaCert.cc_url + links[0].get('href') if links else None

        def get_maintainance_div(cell: Tag) -> Optional[Tag]:
            divs = cell.find_all('div')
            for d in divs:
                if d.find('div') and d.stripped_strings and list(d.stripped_strings)[0] == 'Maintenance Report(s)':
                    return d
            return None

        def get_maintainance_updates(main_div: Tag) -> set:
            possible_updates = list(main_div.find_all('li'))
            maintainance_updates = set()
            for u in possible_updates:
                text = list(u.stripped_strings)[0]
                main_date = datetime.strptime(text.split(' ')[0], '%Y-%m-%d').date() if text else None
                main_title = text.split('– ')[1]
                main_report_link = None
                main_st_link = None
                links = u.find_all('a')
                for l in links:
                    if l.get('title').startswith('Maintenance Report:'):
                        main_report_link = CommonCriteriaCert.cc_url + l.get('href')
                    elif l.get('title').startswith('Maintenance ST'):
                        main_st_link = CommonCriteriaCert.cc_url + l.get('href')
                    else:
                        logging.error('Unknown link in Maintenance part!')
                maintainance_updates.add(CommonCriteriaCert.MaintainanceReport(main_date, main_title, main_report_link, main_st_link))
            return maintainance_updates

        cells = list(row.find_all('td'))
        if len(cells) != 7:
            logging.error('Unexpected number of cells in CC html row.')
            raise

        name = get_name(cells[0])
        manufacturer = get_manufacturer(cells[1])
        manufacturer_web = get_manufacturer_web(cells[1])
        scheme = get_scheme(cells[6])
        security_level = get_security_level(cells[5])
        protection_profiles = get_protection_profiles(cells[0])
        not_valid_before = get_date(cells[3])
        not_valid_after = get_date(cells[4])
        report_link, st_link = get_report_st_links(cells[0])
        cert_link = get_cert_link(cells[2])

        maintainance_div = get_maintainance_div(cells[0])
        maintainances = get_maintainance_updates(maintainance_div) if maintainance_div else set()

        crt = CommonCriteriaCert(category, name, manufacturer, scheme, security_level, not_valid_before, not_valid_after, report_link, st_link, 'html', cert_link, manufacturer_web, protection_profiles, maintainances)

        return crt
