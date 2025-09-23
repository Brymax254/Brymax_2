from admin_tools.dashboard import Dashboard, modules
from admin_tools.menu import items, Menu
from django.urls import reverse
from django.utils.html import format_html
from bookings.models import Booking, Payment, Customer, Tour
import pandas as pd

# ===============================
# CUSTOM ADMIN MENU
# ===============================
class CustomMenu(Menu):
    """Modern admin menu"""
    def init_with_context(self, context):
        self.children += [
            items.MenuItem('Dashboard', reverse('admin:index')),
            items.AppList('Bookings & Payments', exclude=('auth.*', 'admin.*')),
            items.MenuItem('Tours', reverse('admin:bookings_tour_changelist')),
            items.MenuItem('Customers', reverse('admin:bookings_customer_changelist')),
            items.MenuItem('Payments', reverse('admin:payments_payment_changelist')),
            items.MenuItem('Drivers', reverse('admin:bookings_driver_changelist')),
            items.MenuItem('Videos', reverse('admin:bookings_video_changelist')),
            items.MenuItem('Trips', reverse('admin:bookings_trip_changelist')),
            items.MenuItem('Contact Messages', reverse('admin:bookings_contactmessage_changelist')),
        ]


# ===============================
# CUSTOM ADMIN DASHBOARD
# ===============================
class CustomIndexDashboard(Dashboard):
    """Modern SaaS-style dashboard with KPIs, charts, and tables"""
    def init_with_context(self, context):
        # ----------------------------
        # KPI DATA
        # ----------------------------
        total_bookings = Booking.objects.count()
        total_customers = Customer.objects.count()
        total_payments = Payment.objects.filter(status='SUCCESS').count()
        total_revenue = Payment.objects.filter(status='SUCCESS').aggregate(
            total=pd.NamedAgg('amount', 'sum')
        )['total'] or 0

        # ----------------------------
        # KPI CARDS HTML
        # ----------------------------
        kpi_html = format_html("""
        <div style="display:flex; gap:1rem; flex-wrap:wrap; margin-bottom:1rem;">
            <div style="flex:1; min-width:150px; background:#2a9d8f; color:white; padding:1rem; border-radius:8px; text-align:center;">
                <h4>Total Bookings</h4><p style="font-size:1.5rem;">{}</p>
            </div>
            <div style="flex:1; min-width:150px; background:#e76f51; color:white; padding:1rem; border-radius:8px; text-align:center;">
                <h4>Total Customers</h4><p style="font-size:1.5rem;">{}</p>
            </div>
            <div style="flex:1; min-width:150px; background:#f4a261; color:white; padding:1rem; border-radius:8px; text-align:center;">
                <h4>Total Payments</h4><p style="font-size:1.5rem;">{}</p>
            </div>
            <div style="flex:1; min-width:150px; background:#2a9d8f; color:white; padding:1rem; border-radius:8px; text-align:center;">
                <h4>Total Revenue</h4><p style="font-size:1.5rem;">${}</p>
            </div>
        </div>
        """, total_bookings, total_customers, total_payments, total_revenue)

        # ----------------------------
        # MONTHLY CHART DATA
        # ----------------------------
        bookings = Booking.objects.all()
        payments = Payment.objects.filter(status='SUCCESS')

        # Bookings by month
        df_bookings = pd.DataFrame(list(bookings.values('booking_date')))
        if not df_bookings.empty:
            df_bookings['month'] = df_bookings['booking_date'].dt.strftime('%B')
            monthly_bookings = df_bookings.groupby('month').size().to_dict()
        else:
            monthly_bookings = {}

        # Revenue by month
        df_payments = pd.DataFrame(list(payments.values('created_at', 'amount')))
        if not df_payments.empty:
            df_payments['month'] = df_payments['created_at'].dt.strftime('%B')
            monthly_revenue = df_payments.groupby('month')['amount'].sum().to_dict()
        else:
            monthly_revenue = {}

        # ----------------------------
        # COMBINED HTML: KPIs + CHARTS + TABLES
        # ----------------------------
        dashboard_html = format_html("""
        {kpi}

        <div style="display:flex; flex-wrap:wrap; gap:2rem; margin-bottom:2rem;">
            <div style="flex:1; min-width:300px;">
                <h3>Monthly Bookings</h3>
                <div id="bookings_chart"></div>
            </div>
            <div style="flex:1; min-width:300px;">
                <h3>Monthly Revenue</h3>
                <div id="revenue_chart"></div>
            </div>
        </div>

        <div style="overflow-x:auto; margin-bottom:2rem;">
            <h3>Recent Bookings</h3>
            <table style='width:100%; border-collapse:collapse;'>
                <tr style='background:#264653; color:white;'>
                    <th>Customer</th><th>Destination</th><th>Passengers</th><th>Travel Date</th><th>Status</th>
                </tr>
                {recent_bookings_rows}
            </table>
        </div>

        <div style="overflow-x:auto;">
            <h3>Recent Payments</h3>
            <table style='width:100%; border-collapse:collapse;'>
                <tr style='background:#264653; color:white;'>
                    <th>Booking</th><th>Amount</th><th>Method</th><th>Status</th><th>Date</th>
                </tr>
                {recent_payments_rows}
            </table>
        </div>

        <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
        <script>
            var booking_data = {{
                x: {booking_months}, y: {booking_values},
                type:'bar', marker:{{color:'#2a9d8f'}}
            }};
            Plotly.newPlot('bookings_chart',[booking_data], {{margin: {{t:0}}}});

            var revenue_data = {{
                x: {revenue_months}, y: {revenue_values},
                type:'bar', marker:{{color:'#f4a261'}}
            }};
            Plotly.newPlot('revenue_chart',[revenue_data], {{margin: {{t:0}}}});
        </script>
        """,
        kpi=kpi_html,
        booking_months=list(monthly_bookings.keys()),
        booking_values=list(monthly_bookings.values()),
        revenue_months=list(monthly_revenue.keys()),
        revenue_values=list(monthly_revenue.values()),
        recent_bookings_rows=format_html("".join([
            format_html(
                "<tr style='border-bottom:1px solid #ddd;'><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>",
                b.customer.first_name + " " + b.customer.last_name,
                b.destination.name,
                b.num_passengers,
                b.travel_date,
                "Confirmed" if b.is_confirmed else "Cancelled" if b.is_cancelled else "Pending"
            ) for b in Booking.objects.order_by('-booking_date')[:5]
        ])),
        recent_payments_rows=format_html("".join([
            format_html(
                "<tr style='border-bottom:1px solid #ddd;'><td>{}</td><td>{} {}</td><td>{}</td><td>{}</td><td>{}</td></tr>",
                p.booking or '-',
                p.amount, p.currency,
                p.method,
                p.status,
                p.created_at.strftime('%Y-%m-%d')
            ) for p in Payment.objects.order_by('-created_at')[:5]
        ]))
        )

        # ----------------------------
        # APPEND TO DASHBOARD
        # ----------------------------
        self.children.append(modules.HTMLModule(title="Dashboard Overview", content=dashboard_html, collapsible=False))
