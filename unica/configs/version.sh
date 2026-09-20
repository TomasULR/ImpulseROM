#
# Copyright (C) 2025 Salvo Giangreco
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

ROM_VERSION="v1.0-oneui85-alpha2"

ROM_COMMIT="@$(git rev-parse --short HEAD)"
if ! git diff --quiet --ignore-submodules=dirty -- || \
        [ -n "$(git ls-files --others --exclude-standard)" ]; then
    ROM_COMMIT+="-dirty"
fi
