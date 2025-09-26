#!/usr/bin/env python
import os
import sys
import django
import json
import re

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'airport.settings')
sys.path.append('/home/brymax/Documents/airport_destinations')
django.setup()

from bookings.models import Tour


def fix_tour_data():
    """Fix tour data to be valid JSON before migration."""
    print("Fixing tour data...")

    for tour in Tour.objects.all():
        updated = False

        # Fix itinerary field
        if isinstance(tour.itinerary, str):
            try:
                # Try to parse as JSON first
                json_data = json.loads(tour.itinerary)
                tour.itinerary = json_data
                updated = True
                print(f"Fixed itinerary for tour {tour.id}: {tour.title}")
            except json.JSONDecodeError:
                # If not valid JSON, create a simple structure
                if tour.itinerary.strip():
                    lines = [line.strip() for line in tour.itinerary.split('\n') if line.strip()]
                    json_data = []
                    for i, line in enumerate(lines, 1):
                        json_data.append({
                            "day": i,
                            "title": f"Day {i}",
                            "description": line
                        })
                    tour.itinerary = json_data
                    updated = True
                    print(f"Converted itinerary to JSON for tour {tour.id}: {tour.title}")
                else:
                    tour.itinerary = []
                    updated = True

        # Fix inclusions field
        if isinstance(tour.inclusions, str):
            try:
                # Try to parse as JSON first
                json_data = json.loads(tour.inclusions)
                tour.inclusions = json_data
                updated = True
                print(f"Fixed inclusions for tour {tour.id}: {tour.title}")
            except json.JSONDecodeError:
                # If not valid JSON, create a simple list
                if tour.inclusions.strip():
                    items = re.split(r'\n|\*|-', tour.inclusions)
                    items = [item.strip() for item in items if item.strip()]
                    tour.inclusions = items
                    updated = True
                    print(f"Converted inclusions to JSON for tour {tour.id}: {tour.title}")
                else:
                    tour.inclusions = []
                    updated = True

        # Fix exclusions field
        if isinstance(tour.exclusions, str):
            try:
                # Try to parse as JSON first
                json_data = json.loads(tour.exclusions)
                tour.exclusions = json_data
                updated = True
                print(f"Fixed exclusions for tour {tour.id}: {tour.title}")
            except json.JSONDecodeError:
                # If not valid JSON, create a simple list
                if tour.exclusions.strip():
                    items = re.split(r'\n|\*|-', tour.exclusions)
                    items = [item.strip() for item in items if item.strip()]
                    tour.exclusions = items
                    updated = True
                    print(f"Converted exclusions to JSON for tour {tour.id}: {tour.title}")
                else:
                    tour.exclusions = []
                    updated = True

        # Save the tour if any changes were made
        if updated:
            tour.save()
            print(f"Saved tour {tour.id}: {tour.title}")


if __name__ == "__main__":
    fix_tour_data()
    print("Tour data fix completed!")